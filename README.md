# Website Chatbot

The chatbot on [shubhankargoje.com](https://www.shubhankargoje.com), previously called Eeva. Visitors meet it as
Spot, the pen that writes on the site: click the pen and ask about Shubhankar's projects, skills, education or how
to reach him.

## What runs today

- **Model:** Claude Haiku 5.5 through the Anthropic API, answering only from the site's own published content,
  with structured output and a citation for every answer.
- **Backend:** one AWS Lambda behind a function URL, with chat logs in DynamoDB, an archive in Amazon S3, and
  CloudWatch alarms for errors, latency, spend and blocked attacks.
- **Safety:** the same guardrails run in the browser and on the server; questions reach the model as untrusted
  text, and every answer is checked for leaked instructions, links and markup before it is shown. Rate limits and
  a monthly spend cap keep it cheap to run.
- **Testing:** a live suite of 1,077 questions for accuracy and tone, and 672 attacks; nothing leaked.

The project page: [shubhankargoje.com/work/website-chatbot](https://www.shubhankargoje.com/work/website-chatbot/)

## In this repository

The original design document, from when the chatbot was planned as a serverless Amazon Bedrock RAG system
(S3, Lambda and FAISS). The live chatbot's code lives in the site's own repository.
