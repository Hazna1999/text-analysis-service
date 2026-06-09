# Use official Python 3.12 image as base
FROM python:3.12-slim

# Set working directory inside container
WORKDIR /code

# Copy requirements first (for faster rebuilds)
COPY requirements.txt .

# Install all Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files into container
COPY . .

# Tell Python where to find our app
ENV PYTHONPATH=/code