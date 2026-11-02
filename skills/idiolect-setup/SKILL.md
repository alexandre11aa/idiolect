---
name: idiolect-setup
description: Comando idiolect setup. Gera ou atualiza o perfil de estilo de escrita do autor a partir dos textos em data/ (métricas com scripts/idiolect.py e leitura do corpus), preenchendo profile/. Use somente quando o pedido começar com idiolect setup.
---

# idiolect setup: gerar o perfil de estilo

Objetivo: produzir em `profile/` uma descrição do estilo do autor precisa o bastante para que qualquer LLM
escreva sobre **qualquer tema** como ele (mesmo vocabulário, conectivos, ritmo e lógica argumentativa).

## 1. Verifique o corpus

- `data/` precisa ter pelo menos um `.md` com textos do autor. Imagens e outros arquivos são ignorados.
- O cabeçalho YAML é opcional. Sem ele:
  - o idioma é detectado automaticamente, e textos e parágrafos em outro idioma ficam fora;
  - o tipo do texto é inferido pelo nome do arquivo.
- Se `data/` estiver vazia, explique o formato (seção "Seus textos" do `README.md`) e pare.

## 2. Rode a análise

```bash
python scripts/idiolect.py analyze
```

Relate em poucas linhas:
- documentos analisados e palavras;
- documentos ignorados e por quê;
- avisos.

Se um texto com coautoria pesar muito, sugira ao usuário o cabeçalho `coauthored: true` com
`own_sections: [...]`, mas não edite `data/`.

## 3. Leia as evidências

1. **`reports/metrics.md` inteiro.** Anote os traços fortes:
   - o que é muito frequente;
   - o que nunca aparece;
   - como as frases e os parágrafos começam;
   - o que muda entre seções.
2. **Os textos de `data/`.** O corpus pode ser grande. Leia pelo menos, de cada documento, o resumo, a
   introdução, um trecho da revisão, um trecho de resultados/discussão e a conclusão. Leia na íntegra o
   documento mais recente e sem coautoria. Observe o que os números não capturam:
   - a progressão de cada seção;
   - a estrutura dos parágrafos;
   - como apresenta e avalia outros autores;
   - onde aparece a voz própria;
   - como faz transições.

## 4. Escreva o perfil

Crie ou substitua os quatro arquivos abaixo. Cada um começa com
`<!-- generated YYYY-MM-DD from N documents, W words -->`.

**`profile/style.md`**
- Resumo da voz do autor em 5 linhas.
- Registro e tom.
- Pessoa verbal e voz (1ª pessoa? -se? passiva?).
- Ritmo das frases.
- Parágrafos.
- Pontuação.
- Modalização.
- Citações (narrativa × parentética, "Segundo Autor (ano)", verbos de citação).
- Variação por seção.
- **Regras práticas**: lista FAÇA / EVITE, cada item com evidência.
- **Metas numéricas**: tabela com média e faixa p10–p90 (seção 10 do relatório) para:
  - tamanho de frase e de parágrafo;
  - vírgulas por frase;
  - frases que abrem com conectivo;
  - atenuadores;
  - formas com -se;
  - primeira pessoa;
  - citações.

**`profile/lexicon.md`**
- Conectivos preferidos: tabela com função, frequência e posição típica.
- Pares de preferência entre variantes (ex.: "contudo" × "entretanto").
- Inícios de frase característicos.
- Expressões formulaicas.
- Verbos e construções recorrentes.
- Vocabulário característico independente do tema.
- Vocabulário temático: só para quando o tema for o mesmo.
- **Lista negra**: o que o autor nunca ou quase nunca usa. Inclua os marcadores de IA que ele evita (seção 9).

**`profile/argumentation.md`**
- Movimentos retóricos por seção: introdução, revisão, metodologia, resultados/discussão, conclusão.
- Estrutura interna do parágrafo.
- Diálogo com a literatura.
- Encadeamento entre parágrafos.
- Assertividade e posicionamento.
- Uso de dados e exemplos.
- Fechamentos.

**`profile/examples.md`**
- De 2 a 4 trechos reais por tipo de seção, copiados sem alteração.
- Cada trecho com fonte (arquivo e seção) e uma linha "Por que é típico".
- Prefira textos sem coautoria que concentrem vários traços.

Critérios para todo o perfil:
- **Evidência:** toda regra se apoia em um número do `metrics.json` ou em dois ou mais trechos do corpus. Se um
  traço aparece em um só documento, diga isso.
- **Estilo × tema:** estilo é o que se mantém quando o assunto muda. Vocabulário da área é tema e fica à parte.
- **Forma prescritiva:** escreva instruções para quem vai imitar ("Abra parágrafos de revisão com...").
- **Tamanho:** até ~2.500 palavras por arquivo, para caber no contexto junto com a tarefa.

## 5. Teste e refine

1. Escreva um texto de ~400 palavras sobre um tema **fora** da área do autor, seguindo o comando
   `idiolect`, e salve em `drafts/setup-test.md`.
2. Rode `python scripts/idiolect.py compare drafts/setup-test.md`.
3. Se o veredito não for "compatível", identifique a regra do perfil que estava vaga, ausente ou errada,
   corrija-a e teste de novo. Faça no máximo 3 rodadas.

## 6. Entregue

Responda ao usuário com:
- os 5 traços mais marcantes do estilo dele;
- o veredito do teste;
- o texto de teste, para ele dizer o que "não soa como ele" (isso alimenta a calibração da skill
  `idiolect`).
