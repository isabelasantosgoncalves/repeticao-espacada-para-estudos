"""
Exemplo de arquivo WSGI para o PythonAnywhere.

No painel Web do PythonAnywhere, abra o link do "WSGI configuration file"
(algo como /var/www/seuusuario_pythonanywhere_com_wsgi.py), apague o conteúdo
e cole este arquivo, trocando SEUUSUARIO pelo seu nome de usuário.
"""
import os
import sys

PASTA_DO_APP = "/home/SEUUSUARIO/revisa"

if PASTA_DO_APP not in sys.path:
    sys.path.insert(0, PASTA_DO_APP)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(PASTA_DO_APP, ".env"))

from app import app as application  # noqa: E402,F401
