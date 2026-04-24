Como criar um ambiente virtual e utiliza-lo.

1. Instalar o python em uma versão 3.12 ou superior, e adicionar o PATH
2. executar o comando "python -m venv venv" para criar a pasta venv
3. executar o comando "Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process"
4. Executar o comando ".\venv\Scripts\Activate.ps1"

Após criar e abrir o ambiente virtual, executar: 
- pip install django

E para saber se o django tá rodando: 
- python manage.py runserver

Caso decidam, ou precisem fazer migrations (em ordem):
1. python manage.py makemigrations
2. python manage.py migrate
