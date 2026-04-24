Como criar um ambiente virtual e utiliza-lo em um computador não da uvv.

Instalar o python em uma versão 3.12 ou superior, e adicionar o PATH
executar o comando "python -m venv venv" para criar a pasta venv
executar o comando "Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process"
Executar o comando ".\venv\Scripts\Activate.ps1"
Após criar e abrir o ambiente virtual, executar:

pip install django
E para saber se o django tá rodando:

python manage.py runserver
Caso decidam, ou precisem fazer migrations (em ordem):

python manage.py makemigrations
python manage.py migrate
