# Use an official lightweight Python runtime
FROM python:3.11-slim

# Establish the internal working directory
WORKDIR /app

# Copy the application assets into the container
COPY . .

# Install production dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Launch the pipeline orchestrator
ENTRYPOINT ["python", "pipeline_runner.py"]