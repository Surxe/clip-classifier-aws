# Design notes: clip-classifier-aws

A deeper writeup of the architecture, the decisions behind it, and the operational
lessons from building it. The [README](../README.md) is the high-level overview; this is
the "why", intended for a technical reader who wants to probe the choices.

## Context

This is one of three gap-closing projects built for an AI/ML Engineer application. It
takes an existing, working piece of code - the constrained LLM classifier from the
`clip-db` project, which shells out to a local `claude` CLI - and re-implements it as a
cloud-native, serverless service on AWS. The point was hands-on experience with Bedrock,
Lambda, container images, IAM, and infrastructure-as-code, not to invent new
classification logic.

### Goals

- Run the classifier as a managed, serverless HTTP service on AWS.
- Get real, hands-on exposure to Amazon Bedrock, Lambda, API Gateway, IAM, and SAM.
- Package the function as a Docker container image for Docker experience.
- Keep the classification behavior identical to the original.

### Non-goals

- **No ECS / Fargate.** Serverless (Lambda) only, deliberately.
- No new model or prompt research - the prompt and schema are ported unchanged.
- Not a production service: no auth, no custom domain, no CI/CD.

## What was ported, and what changed

The classification logic came over from `clip-db` almost verbatim:

- `tags.py` and `tags.json` - the controlled vocabulary and its loader - are unchanged.
- `classify.py` kept the system prompt and the JSON schema (a `tags` array constrained to
  an enum of the vocabulary, plus a nullable `proposed_tag`).

The **only** substantive change is the model runner. The original built its classifier
around an injectable `runner(*, prompt, system, schema, model)` seam (so tests could stub
the model). That seam made the port clean: the local `claude` CLI runner was replaced with
a Bedrock `InvokeModel` runner, and nothing else in the classification flow had to change.

## Key decisions

### 1. Container-image Lambda instead of a zip package

Lambda supports zip archives and container images. The container image was chosen
specifically to get Docker experience and because it makes dependencies explicit in a
`Dockerfile`. The base image is the AWS-provided `public.ecr.aws/lambda/python:3.13`,
which already includes boto3, so the image stays small. SAM builds the image, pushes it
to a managed ECR repository, and points the Lambda at it.

### 2. Structured output via a forced tool call

The classifier must return JSON that validates against a schema whose `tags` field is an
enum of ~380 allowed values. On Bedrock, the reliable way to constrain Claude to a schema
is to define a single tool whose `input_schema` *is* the classification schema and force
`tool_choice` to that tool. Claude then emits a `tool_use` block whose `input` is
schema-valid JSON, which the runner returns directly. This is robust across Claude models
on Bedrock and needs no extra SDK - just a raw `InvokeModel` body via boto3.

### 3. Vocabulary bundled in the image (not S3)

The original plan included storing the vocabulary in S3. It is instead bundled into the
container image as `tags.json`. Trade-off:

- **Bundled (chosen):** the vocabulary is versioned atomically with the code and image;
  no runtime S3 read, no extra IAM, no failure mode if S3 is unreachable. The cost is
  that changing the vocabulary requires a rebuild and redeploy.
- **S3 (future):** the vocabulary could be updated without redeploying, and results could
  be logged to S3 for later analysis. This is the natural next enhancement (see below).

For a single-maintainer learning project where the vocabulary changes rarely, bundling was
the simpler, more reliable choice. S3 is documented as future work rather than built, to
keep the description of this project accurate.

### 4. Least-privilege IAM

The Lambda execution role is granted only `bedrock:InvokeModel`. It could be tightened
further by scoping the `Resource` from `"*"` to the specific model and inference-profile
ARNs; that is noted as a hardening step. (The role also briefly carried
`aws-marketplace:Subscribe` / `ViewSubscriptions` during debugging - see the Marketplace
lesson below - which turned out to be unnecessary once the model was subscribed
account-wide, and can be removed.)

### 5. Infrastructure-as-code with SAM

The entire stack - the Lambda, its IAM role, the HTTP API, and the wiring between them -
is declared in `template.yaml` and deployed with `sam deploy`. Nothing is clicked together
by hand in the console, so the environment is reproducible and reviewable.

## Operational lessons

Two Bedrock-specific gotchas cost real time and are worth recording:

1. **Anthropic use-case form.** Before any Claude model on Bedrock can be invoked, the
   account must submit a one-time Anthropic "use case details" form. It is separate from
   the (now auto-approved) model-access toggle, and easy to miss - the first invoke fails
   with a `ResourceNotFoundException` that says the form has not been submitted. The form
   requires a company name and website URL and rejects "Individual"; a personal GitHub
   profile URL satisfies the validator honestly.

2. **The first invoke must come from a Marketplace-capable principal.** Bedrock models are
   AWS Marketplace subscriptions under the hood, and the very first invoke triggers the
   subscription. A Lambda execution role with only `bedrock:InvokeModel` cannot complete
   it and fails with an `AccessDeniedException` naming `aws-marketplace:Subscribe`. The
   fix that actually worked was to invoke the model once from an admin principal (which has
   Marketplace permissions), which subscribed the model account-wide; after that, the
   Lambda role's plain `bedrock:InvokeModel` was sufficient. Adding Marketplace permissions
   to the Lambda role did not help, because the block was completing the subscription, not
   authorization to invoke.

## Cost model

- **Lambda, API Gateway (HTTP API), ECR:** within the AWS free tier for hobby-scale use.
- **Bedrock:** no free tier, billed per token. Claude Haiku 4.5 is the cheapest current
  model and is more than capable for short-text constrained classification; each request
  is a fraction of a cent. A billing budget/alarm was set as a guardrail.

Because the endpoint is public and Bedrock is metered, the stack is torn down with
`sam delete` when not actively being demonstrated.

## Security note

The `POST /classify` endpoint is public and unauthenticated - appropriate for a
short-lived demo, not for anything left running. Hardening options, in rough order:

- Put an API key or IAM authorization in front of the HTTP API.
- Add request size limits and basic input validation beyond the current empty-description
  check.
- Scope the Lambda role's `bedrock:InvokeModel` resource to the exact model ARNs.

## Future work

- **S3-backed vocabulary and result logging** - load `tags.json` from S3 at cold start so
  the vocabulary can change without a redeploy, and write each classification to S3 for
  later analysis or evaluation.
- **Batch endpoint** - the original `clip-db` classifier also supports classifying many
  clips in one call (a `results` array keyed by id); that path was not ported here.
- **Authentication and tighter IAM** as described in the security note.
- **A small evaluation set** to measure tagging quality and catch regressions when the
  prompt, model, or vocabulary changes.
