# Imagem para rodar a interface web sem instalar Python na máquina.
#   docker build -t minifs . && docker run --rm -p 5000:5000 minifs
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY minifs ./minifs

# Usuário sem privilégios: o servidor não precisa de root.
RUN useradd --create-home minifs
USER minifs

EXPOSE 5000
CMD ["python", "-m", "minifs.web", "--host", "0.0.0.0", "--port", "5000"]
