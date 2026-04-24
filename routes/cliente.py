from flask import Blueprint , render_template


cliente_route = Blueprint('cliente' , __name__)

@cliente_route.route ('/')
def lista_clientes():
    """Listar Clientes"""
    return render_template ('clientes.html' , clientes = []) # Substitua [] por uma lista de clientes reais

@cliente_route.route ('/' , methods = {'POST'})
def inserir_clientes():
    """Inserir os dados do cliente"""
    pass

@cliente_route.route ('/new' , methods = {'GET'})
def form_cliente():
    """Formulário para cadastrar um cliente"""
    return render_template ('form_cliente.html')

@cliente_route.route ('/<int:cliente_id>' , methods = {'GET'})
def detalhe_cliente(cliente_id):
    """exibir detalhes do cliente"""
    pass

@cliente_route.route ('/<int:cliente_id>/edit')
def form_edit_cliente(cliente_id):
    """formulario para editar as informações dos clientes"""
    pass

@cliente_route.route ('/<int:cliente_id>/update' , methods = {'PUT'})
def update_cliente(cliente_id):
    """atualizar informações do cliente"""
    pass

@cliente_route.route ('/<int:cliente_id>/delete' , methods = {'DELETE'})
def delete_cliente(cliente_id):
    """deletar cliente"""
    pass