# tags.json - the controlled vocabulary

`app/tags.json` holds the fixed set of tags the classifier is constrained to. It is loaded
once at cold start by `tags.py` (`load_vocab`) and flattened into the JSON-schema enum the
model must choose from.

## Structure

The vocabulary has two tiers:

- **generic** - tags that apply to any game (e.g. `clutch`, `fail`, `highlight`).
- **games** - tags scoped to a named game. The game's display name is itself a tag, and
  every item under it is a tag. Items are organised into named *groups* (e.g. weapons /
  modules / abilities) purely for readability - the group labels are **not** tags.

```json
{
  "generic": ["clutch", "fail", "..."],
  "games": {
    "War Robots Frontiers": {
      "groups": {
        "weapons": ["...", "..."],
        "modules": ["...", "..."]
      }
    }
  }
}
```

`load_vocab` also accepts a legacy `{"tags": [...]}` dict or a bare list, but the structured
form above is what this project uses.

## Why it's duplicated with clip-db

This `tags.json` is a **copy** of the vocabulary in the `clip-db` project, not a shared or
synced source. Two reasons:

1. **Ported verbatim.** The classification logic (`classify.py`, `tags.py`, `tags.json`)
   was lifted from `clip-db` almost unchanged - only the model runner was swapped (local
   `claude` CLI -> Bedrock `InvokeModel`). The vocabulary came along with it.
2. **Bundled into the container image.** By design (see [DESIGN.md](DESIGN.md), decision 3)
   the vocabulary is baked into the Lambda's Docker image as `app/tags.json` rather than
   read from S3 at runtime. That keeps it versioned atomically with the code and removes a
   runtime dependency - at the cost of it being a physical duplicate of clip-db's copy.

## We don't keep the two in sync

`clip-classifier-aws` is a learning / portfolio project, not a production service. The
point was hands-on AWS experience (Bedrock, Lambda, IAM, SAM, Docker), **not** maintaining
the tag vocabulary. So when `clip-db`'s `tags.json` changes, this copy is intentionally
**not** updated - the exact tag list is immaterial to what this project demonstrates. If
this ever became more than a demo, the natural fix is the S3-backed vocabulary noted as
future work in DESIGN.md.
