# Imagen base oficial de Apify con Python + Playwright/Chromium preinstalado.
FROM apify/actor-python-playwright:3.11

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && python3 -m playwright install --with-deps chromium

COPY . ./

CMD ["python3", "-m", "src.main"]
