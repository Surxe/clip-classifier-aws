FROM public.ecr.aws/lambda/python:3.13

# boto3 is already in the base image; requirements.txt is here so adding deps
# later (e.g. the anthropic SDK when we port the real classifier) is a one-line change.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py classify.py tags.py tags.json ./

# module.function that Lambda invokes
CMD ["app.handler"]
