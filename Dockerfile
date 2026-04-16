FROM python:3.11-slim

WORKDIR /app

# Install Cloud Custodian and dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy policies and handler
COPY policies/ /app/policies/
COPY handler.py /app/handler.py

# Lambda runtime interface
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["handler.lambda_handler"]
