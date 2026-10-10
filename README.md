# Kuro Inventory Pricing — vitrine pública

Mini-SaaS single-tenant de precificação e controle de estoque com **IA local** (LLaMA 3.1 8B via Ollama), empacotado em **um executável** que se atualiza por um canal **assinado com Ed25519**.

> **O código completo é fechado.** Este repositório contém só documentação de arquitetura e trechos isolados. Para ver mais: berlofaspike@gmail.com.

## Comece por aqui

- **[`case-study.md`](case-study.md)**: estudo de caso completo, com resumo em uma tela, modelo de ameaças, 7 diagramas Mermaid, decisões técnicas profundas (seções 3.1 a 3.10), o que foi medido, os erros que meus testes acharam e o que **não** foi provado.
- **[`assets/`](assets)**: capturas reais do app em execução (dados sintéticos): painel, conferência de colunas, análise do LLaMA local e relatório de e-mail.
- **[`amostras/`](amostras)**: trechos autocontidos que ilustram a lógica (guarda-corpo de preço, host local da IA, disjuntor, ingestão com Polars, empacotamento com PyArmor, verificação do OTA).

## Em quatro linhas

| Tema | Decisão |
|---|---|
| Privacidade | o cliente de IA só aceita host local; dado de planilha é dado, saída do modelo é dado hostil |
| Dinheiro | o LLM propõe um ajuste de ±30%; o código calcula e corta em `[piso, teto]` de margem |
| Entrega | PyInstaller `--onefile` + PyArmor; ofuscação tratada como atrito, não como segredo |
| Atualização | manifesto Ed25519 com hash, tamanho e URL assinados; só versão maior; 1 byte diferente apaga tudo |

## Rodar os trechos

Cada arquivo de `amostras/` importa só da biblioteca padrão, de outros trechos da mesma pasta (`erros.py`, `ota_manifesto_ed25519.py`) e de `httpx`, `polars`, `fastexcel` ou `cryptography`. Python 3.13.

## Licença

Todos os direitos reservados; uso como entrada ou treino de IA vedado. Veja [`LICENSE`](LICENSE).
