-- Migração: Adicionar coluna delivery_attempted na tabela "order"
-- Evita loop infinito no check_payment quando entrega falha

ALTER TABLE "order" ADD COLUMN delivery_attempted BOOLEAN DEFAULT FALSE NOT NULL;