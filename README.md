# idiolect

Faça uma LLM escrever **como você**. Coloque seus textos acadêmicos (TCC, dissertação, tese, artigos) em
`data/`, rode o comando de configuração, e depois peça textos sobre qualquer tema no seu estilo:
mesmo vocabulário, conectivos, ritmo e forma de argumentar.

O processo é reproduzível: qualquer pessoa pode clonar este repositório, trocar os textos de `data/` pelos
seus e obter o próprio perfil.

## Uso rápido

1. **Coloque seus textos em `data/`**, um arquivo `.md` por trabalho (detalhes abaixo).
2. **Abra a pasta num agente de IA** com acesso aos arquivos (Claude Code, Codex, Cursor, Gemini...) e digite:
   > /idiolect-setup
3. **Peça seus textos:**
   > /idiolect escreva uma introdução sobre o uso de energia solar em escolas públicas, ~500 palavras

Os comandos são texto no início da mensagem, definidos no `AGENTS.md`, e funcionam em qualquer agente. Sem
`/idiolect` ou `/idiolect-setup`, o agente trata o pedido como uma conversa comum. As instruções de cada comando
ficam em `skills/`:

- **`/idiolect-setup`** roda a análise, lê seus textos, escreve o perfil em `profile/` e faz um texto de teste.
- **`/idiolect <pedido>`** escreve, mede o resultado contra os seus textos, corrige o que destoa e entrega.
  Também revisa textos ("isso soa como eu?") e ajusta o perfil quando você diz o que não soou como você.

Requisito: Python 3.9 ou superior. Não há nada para instalar.

## Como funciona

```
data/*.md ──► idiolect.py analyze ──► reports/metrics.md ──┐
    └──────────────── leitura pela LLM ────────────────────┴──► profile/*.md
                                                                     │
pedido ──► LLM escreve seguindo profile/ ──► idiolect.py compare ──► correções ──► texto final
```

O trabalho se divide em três partes:

1. **Métricas (script, determinístico):**
   - tamanho de frases e parágrafos;
   - conectivos e a posição deles;
   - inícios de frase;
   - atenuadores e intensificadores;
   - voz passiva, formas com "-se" e primeira pessoa;
   - pontuação;
   - expressões recorrentes;
   - padrões de citação;
   - diferenças entre seções.
2. **Perfil (LLM):** regras de estilo, léxico, estrutura argumentativa e trechos reais anotados, sempre
   apoiados nas métricas ou em exemplos do corpus.
3. **Validação (script):** `compare` mede um texto contra o seu corpus. O veredito combina três sinais:
   - indicadores fora da sua faixa normal;
   - o Delta de Burrows (uso de palavras funcionais, um indicador clássico de autoria);
   - expressões com "cara de IA" que você não usa.

## Seus textos

- **Formato:** um `.md` por trabalho, direto em `data/`. Imagens e outros arquivos são ignorados.
- **Títulos:** use `#`, `##` nas seções. "Introdução", "Referencial teórico", "Metodologia", "Resultados",
  "Discussão" e "Conclusão/Considerações finais" são reconhecidos com ou sem numeração.
- **Descartado automaticamente:**
  - capa e folha de rosto;
  - listas de siglas, agradecimentos, referências e apêndices;
  - legendas de figuras e tabelas, linhas "Fonte:" e legendas de fórmulas;
  - tabelas, equações e código;
  - resumos em outros idiomas.
- **Citações de outros autores:** as diretas também saem da análise, por serem palavras alheias. Use `>`
  nas longas; as curtas entre aspas são detectadas sozinhas.
- **Textos em outro idioma** são ignorados. O idioma é detectado automaticamente.
- **Quanto texto:** o recomendado é a partir de 20 mil palavras. Uma dissertação já basta.

**Cabeçalho opcional:** tudo funciona sem cabeçalho. Use-o quando precisar de controle, por exemplo para
textos com coautores:

```yaml
---
type: article            # undergraduate_thesis | dissertation | doctoral_thesis | article | other
year: 2023
language: pt-BR
coauthored: true
own_sections: [introduction, literature_review]   # só estas seções entram na análise
exclude_sections: []      # ex.: um capítulo muito reescrito pelo orientador
include: true             # false tira o texto da análise
---
```

Nomes de seção válidos: `abstract`, `introduction`, `literature_review`, `methodology`, `results`,
`results_discussion`, `discussion`, `conclusion`, `other`.

## Comandos

O agente roda os comandos sozinho, mas você também pode usá-los diretamente:

```bash
python scripts/idiolect.py analyze                   # gera reports/metrics.md, metrics.json, vocabulary.json
python scripts/idiolect.py compare drafts/texto.md   # mede um texto contra o seu estilo
```

`reports/metrics.md` é um retrato objetivo da sua escrita e vale a pena ler.

**Outro idioma:** copie `scripts/lang/pt-BR.txt` (por exemplo, para `en.txt`), traduza as listas e rode
`analyze --lang en`.

## Estrutura

```
idiolect/
├── README.md
├── AGENTS.md            instruções para qualquer agente
├── CLAUDE.md            aponta para o AGENTS.md (Claude Code)
├── skills/
│   ├── idiolect-setup/SKILL.md
│   └── idiolect/SKILL.md
├── scripts/
│   ├── idiolect.py      analyze | compare
│   └── lang/pt-BR.txt   listas de palavras (editáveis)
├── data/                seus textos (.md)
├── reports/             gerado por analyze
└── profile/             gerado pelo agente (style, lexicon, argumentation, examples)
```

## Limitações e uso responsável

- **O que as métricas medem:** léxico, ritmo e conectivos. A lógica argumentativa depende da leitura da LLM
  e dos exemplos, por isso o seu feedback na calibração importa.
- **Estimativas:** voz passiva e primeira pessoa são detectadas por heurística.
- **Voz de outras pessoas:** textos muito revisados por orientadores ou coautores carregam parte da voz deles.
- **Conteúdo:** o perfil imita a forma, não o conteúdo. As skills nunca inventam referências e marcam
  `[CITAÇÃO: ...]` onde falta fonte.
- **Regras acadêmicas:** confira as normas da sua instituição ou do periódico sobre uso de IA e declare o
  uso quando for exigido.
