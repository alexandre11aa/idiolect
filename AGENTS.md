# AGENTS.md

Instruções para qualquer agente de IA que trabalhe neste repositório (Claude Code, Codex, Cursor, Gemini...).

**idiolect** gera o perfil do estilo de escrita acadêmica de um autor a partir dos textos dele e usa esse
perfil para escrever sobre qualquer tema como o autor escreveria.

## Mapa

| Caminho | O que é | Quem altera |
|---|---|---|
| `data/` | textos do autor em Markdown (`.md`) | só o autor |
| `scripts/idiolect.py` | `analyze` (métricas), `compare` (mede um texto) | - |
| `scripts/lang/pt-BR.txt` | listas de conectivos, atenuadores, marcadores de IA etc. | o autor, se quiser |
| `reports/` | saída de `analyze` | só o script |
| `profile/` | o perfil de estilo | o agente, via skills |
| `skills/` | os dois comandos (`/idiolect-setup` e `/idiolect`), escritos como skills | - |
| `drafts/` | rascunhos e relatórios de comparação | o agente |

## Comandos

Este repositório só age sobre pedidos que **comecem com um dos comandos abaixo**. O comando é um texto digitado
no início da mensagem, e vale em qualquer agente (Claude Code, Codex, Cursor, Gemini...). Ao receber um, leia
o arquivo indicado e siga-o do começo ao fim.

| Comando | Faz | Siga |
|---|---|---|
| `/idiolect-setup` | gera ou atualiza o perfil a partir de `data/` | `skills/idiolect-setup/SKILL.md` |
| `/idiolect <pedido>` | escreve, revisa ou calibra no estilo do autor | `skills/idiolect/SKILL.md` |

Exemplo: `/idiolect escreva uma introdução sobre o uso de energia solar em escolas públicas, ~500 palavras`.

Mensagem sem esses comandos: **não** aplique o perfil nem as skills. Responda como em qualquer conversa
comum e, se o pedido parecer ser de escrita no estilo do autor, diga que é preciso usar `/idiolect`.

Se `profile/style.md` não existir e o usuário usar `/idiolect`, peça que ele rode `/idiolect-setup` antes
(ou execute-o, se ele autorizar).

## Regras

- Não edite `data/` nem `reports/` à mão.
- Antes de escrever no estilo do autor, leia todos os arquivos de `profile/`.
- Nunca invente referências, dados ou citações. Use `[CITAÇÃO: ...]` onde faltar fonte.
- Nomes de arquivos em inglês; conteúdo em português.
- O script usa só a biblioteca padrão do Python 3.9+. Não adicione dependências.
