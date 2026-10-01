FROM python:3.12-slim
ENV DATABASE_URL=postgres://db/shop
ENV MAX_PER_ORDER=10
COPY shop /app/shop
CMD ["uvicorn", "shop.api:app", "--host", "0.0.0.0"]
