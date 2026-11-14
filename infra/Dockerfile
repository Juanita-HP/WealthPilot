# Lambda container image (pandas and numpy exceed the zip size limit).
FROM public.ecr.aws/lambda/python:3.13

COPY requirements-lambda.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements-lambda.txt

COPY wealthpilot ${LAMBDA_TASK_ROOT}/wealthpilot

CMD ["wealthpilot.aws.lambda_handler.lambda_handler"]
