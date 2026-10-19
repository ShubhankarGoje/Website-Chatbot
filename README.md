# Eeva: meeting scheduler chatbot

Eeva is a chat assistant that lives on your website and books meetings with you. Visitors
say when they'd like to meet. Eeva checks your Google Calendar for free time, offers a few
slots in the visitor's own timezone, and collects their name, email and topic. Once they
confirm, it books the meeting and emails them a Google Calendar invite with a Meet link.

Everything server-side runs on AWS (serverless, no always-on compute), following the
[Eeva design doc](./Design%20Document%20—%20Serverless%20AWS%20Bedrock%20RAG%20Chatbot%20(S3%20+%20Lambda%20+%20FAISS).pdf).

```
 your website                       AWS (us-west-2)                              Google
┌──────────────────┐  POST /chat  ┌──────────────┐   ┌──────────────────────┐
│ <eeva-scheduler> │ ───────────▶ │ API Gateway  │──▶│ Lambda (Python 3.13) │──▶ Calendar API
│  web component   │ ◀─────────── │ HTTP API     │   │  app.py / agent.py   │    (free/busy,
└──────────────────┘   reply      │ CORS+throttle│   └──────┬─────────┬─────┘     create event)
                                  └──────────────┘          │         │
                                              Amazon Bedrock│         │Secrets Manager
                                           (Claude Haiku 5.5)         (Google OAuth token)
```

## Repository layout

| Path | What it is |
| --- | --- |
| `backend/template.yaml` | AWS SAM template: HTTP API, Lambda, IAM, log group, 5xx alarm |
| `backend/src/app.py` | Lambda handler: validates the request, returns the reply |
| `backend/src/agent.py` | Claude tool-use loop, system prompt, `find_available_slots` / `book_meeting` tools |
| `backend/src/scheduling.py` | Availability rules (working hours, buffers, notice, DST), pure and unit tested |
| `backend/src/google_calendar.py` | Small Google Calendar REST client (standard library only) |
| `backend/src/config.py` | Settings from environment variables |
| `backend/tests/` | pytest suite |
| `frontend/eeva-scheduler.js` | The embeddable chat widget (one file, no dependencies) |
| `frontend/index.html` | Demo page |
| `scripts/google_auth.py` | One-time Google authorization; stores the token in Secrets Manager |
| `scripts/local_server.py` | Runs the widget and API locally for testing |

## Setup

### 1. Prerequisites

- AWS account, [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) configured (`aws sts get-caller-identity` works)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- Python 3.13 (or Docker, to build with `sam build --use-container`)
- The Google account whose calendar people should book into

### 2. Enable Claude in Amazon Bedrock

In the AWS console, open **Bedrock → Model access** in **us-west-2** and enable **Claude Haiku 5.5**
(`anthropic.claude-haiku-5-5`). Haiku follows the design doc's choice of a fast, low-cost model.
To use another model, set the `ModelId` parameter, e.g. `anthropic.claude-sonnet-5-5`.

### 3. Create Google OAuth credentials

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project (e.g. "Eeva").
2. **APIs & Services → Library** → enable **Google Calendar API**.
3. **APIs & Services → OAuth consent screen**: choose *External*, fill in the app name and your email.
   Add the scopes `.../auth/calendar.freebusy` and `.../auth/calendar.events`.
4. **Publish the app** ("Publishing status → In production"). While an app is in *Testing*, Google
   expires its refresh tokens after 7 days and Eeva would stop working. Google doesn't need to verify
   an app that only you use. You'll see an "unverified app" warning when you authorize; that's expected.
5. **Credentials → Create credentials → OAuth client ID**, application type **Desktop app**.
   Download the JSON (e.g. `client_secret.json`; it's git-ignored).

### 4. Authorize Eeva and store the token in AWS

```bash
pip install boto3
python scripts/google_auth.py --client-secrets client_secret.json
```

This opens your browser, asks you to allow calendar access, and saves
`{client_id, client_secret, refresh_token}` to the Secrets Manager secret `eeva/google-calendar`
in us-west-2. Eeva only asks for *free/busy* reads (it never sees your event titles or details) and
permission to create events.

### 5. Deploy the backend

```bash
cd backend
sam build            # or: sam build --use-container
sam deploy --guided  # first time; afterwards just `sam deploy`
```

Accept the defaults or override parameters (see [Configuration](#configuration)). The stack output
`ChatEndpoint` is your API URL, e.g. `https://abc123.execute-api.us-west-2.amazonaws.com/chat`.

### 6. Put the widget on your website

Copy `frontend/eeva-scheduler.js` to your site's static files and add:

```html
<script type="module" src="/eeva-scheduler.js"></script>
<eeva-scheduler api-url="https://abc123.execute-api.us-west-2.amazonaws.com/chat"
                owner-name="Shubhankar"></eeva-scheduler>
```

This adds a floating **Book a meeting** button. For a dedicated booking page, add the `inline`
attribute and the chat renders in the page flow instead.

**React + Vite (Amplify):** put `eeva-scheduler.js` in `public/`, add the `<script type="module">`
tag to `index.html`, then use `<eeva-scheduler api-url="..." owner-name="Shubhankar" />` in any
component.

Customize the look with CSS variables on the element:

```css
eeva-scheduler { --eeva-accent: #0f766e; --eeva-font: "Inter", sans-serif; --eeva-radius: 12px; }
```

Set `theme="light"` or `theme="dark"` to force a theme (it otherwise follows the visitor's OS setting).
For analytics, listen for the `eeva:booked` event:
`document.addEventListener("eeva:booked", e => console.log(e.detail))`.

Make sure your site's origin is in the `AllowedOrigins` parameter, or the browser will block the calls.

## Configuration

All settings are SAM parameters (`sam deploy --parameter-overrides Key=Value ...`):

| Parameter | Default | Meaning |
| --- | --- | --- |
| `AllowedOrigins` | `https://shubhankargoje.com,https://www.shubhankargoje.com` | Sites allowed to call the API (CORS) |
| `OwnerName` | `Shubhankar` | Your name, as Eeva refers to you |
| `OwnerTimezone` | `America/Los_Angeles` | Timezone your working hours are in |
| `WorkingHours` | `mon-fri 09:00-17:00` | Bookable hours, e.g. `mon-thu 10:00-12:00,14:00-17:00; fri 10:00-12:00` |
| `MeetingDurations` | `15,30,60` | Allowed meeting lengths in minutes |
| `BufferMinutes` | `10` | Gap kept around existing events |
| `MinNoticeHours` | `12` | How soon a meeting can be booked |
| `MaxDaysAhead` | `30` | How far ahead a meeting can be booked |
| `CalendarIds` | `primary` | Calendars checked for conflicts (comma-separated); bookings go on the first |
| `ModelId` | `anthropic.claude-haiku-5-5` | Bedrock model |
| `GoogleSecretName` | `eeva/google-calendar` | Secrets Manager secret from step 4 |

To include a work or shared calendar in conflict checks, add its ID (from Google Calendar →
Settings → *Integrate calendar*) to `CalendarIds`, e.g. `primary,you@company.com`.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-dev.txt

# Unit tests (no AWS or Google access needed)
cd backend && python -m pytest && cd ..

# End to end against real Bedrock + your real calendar.
# Bookings made here are real.
python scripts/google_auth.py --client-secrets client_secret.json --out google-credentials.json
GOOGLE_CREDENTIALS_FILE=google-credentials.json AWS_REGION=us-west-2 python scripts/local_server.py
# open http://127.0.0.1:8787
```

## How it works

- **Conversation state lives in the browser.** Each request sends the visible chat history, and
  nothing is stored server-side. Refreshing the page starts over, as the design doc specifies.
- **Claude only proposes; the server decides.** `book_meeting` re-checks everything before it creates
  the event: allowed length, working hours, notice period, booking horizon, and a fresh free/busy
  lookup. A manipulated conversation can't book outside your rules.
- **Privacy.** Eeva reads your calendar through the free/busy API, which returns busy time ranges
  only, never titles, attendees or descriptions.
- **Abuse limits.** API Gateway throttling (5 req/s, burst 10). Messages are capped at 2,000
  characters and conversations at 30 messages. Each email can hold at most 2 upcoming meetings
  booked through Eeva (tracked with a private property on the calendar event, so no database is needed).
- **Guardrails.** The system prompt keeps Eeva on scheduling and has it confirm details before booking.
  Claude must get an explicit "yes" before calling `book_meeting`.
- **Monitoring.** Lambda logs go to CloudWatch (`/aws/lambda/eeva-chat`, 30-day retention). An alarm
  fires when the API returns 3 or more 5xx errors in 5 minutes. Attach an SNS topic to it to get emails.

## Cost

At personal-site traffic, Lambda and API Gateway stay within the free tier. Secrets Manager is about
$0.40 per secret per month. Bedrock charges per token: a typical booking conversation is a few
thousand tokens on Claude Haiku, a fraction of a cent. See [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/).

## Ideas for later

- Merge with the RAG "ask about my projects" Eeva from the design doc (add a `search_portfolio` tool).
- Let guests reschedule or cancel through Eeva instead of declining the invite.
- Send yourself a summary (SNS or SES) whenever someone books.
