FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt google-genai
COPY . .
ENTRYPOINT ["python", "-m", "qa_agents"]
CMD ["run", "--usecase", "inputs/usecases/"]
