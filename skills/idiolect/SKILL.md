---
name: idiolect
description: Comando /idiolect <pedido>. Escreve textos acadêmicos sobre qualquer tema no estilo pessoal do autor (vocabulário, conectivos, ritmo, argumentação), seguindo o perfil em profile/ e medindo o resultado com idiolect.py compare. Também revisa textos e calibra o perfil com o feedback do autor. Use somente quando o pedido começar com /idiolect.
---

# /idiolect: escrever no estilo do autor

O texto depois de `/idiolect` é o pedido. Exemplos: "escreva uma introdução sobre energia solar em escolas
públicas, ~500 palavras", "revise este texto", "não soou como eu porque...".

## 0. Localize os arquivos

Trabalhe a partir da raiz do repositório (onde está `scripts/idiolect.py`): use `profile/` e
`python scripts/idiolect.py compare`.

Se `profile/style.md` não existir, o perfil ainda não foi gerado. Siga antes o comando `/idiolect-setup`.

## 1. Leia o perfil

Leia sempre, inteiros:
- `profile/style.md`
- `profile/lexicon.md`
- `profile/argumentation.md`
- `profile/examples.md`

Releia no `argumentation.md` a parte da seção pedida.

## 2. Entenda o pedido

Defina, ou infira e declare em uma linha:
- tema e ideia central;
- tipo de texto e seção (introdução, revisão, discussão, resumo, projeto...);
- extensão;
- fontes que o usuário forneceu.

Se faltar algo essencial e o usuário estiver presente, faça uma única pergunta.

## 3. Escreva

- Siga os movimentos retóricos da seção (`argumentation.md`).
- Use os conectivos e inícios de frase preferidos, nas posições preferidas (`lexicon.md`).
- Nada da lista negra.
- Mire nas metas numéricas de `style.md`: frase, parágrafo, vírgulas, modalização, formas com -se, pessoa
  verbal.
- Se `style.md` tiver a seção "Traços não normativos (ATIVOS)", aplique esses traços na dosagem indicada lá. Eles
  são preferência declarada do autor, não erros a corrigir.
- Não leve o vocabulário temático do autor para outros temas.
- **Nunca invente referências, dados ou citações.** Use só as fontes do usuário. Onde o estilo pediria uma
  citação e não houver fonte, escreva `[CITAÇÃO: o que precisa ser sustentado]`.
- Salve o rascunho em `drafts/<tema-curto>.md`, criando a pasta se preciso.

## 4. Meça e corrija

```bash
python scripts/idiolect.py compare drafts/<tema-curto>.md
```

Corrija, nesta ordem:
1. Expressões com cara de IA.
2. Conectivos que o autor quase nunca usa.
3. Indicadores **FORA**.
4. Indicadores em **atenção**.
5. Inícios de frase repetidos.

Ignore os desvios explicados pelo pedido, como "citações" num texto sem fontes. Repita até o veredito ser
"compatível com o seu estilo", com no máximo 3 rodadas.

## 5. Entregue

Entregue o texto final. Depois dele, em até 4 linhas:
- o veredito;
- os desvios que restaram e por quê;
- as marcações `[CITAÇÃO: ...]` pendentes.

Lembre que o conteúdo e as fontes são responsabilidade do autor.

---

## Revisar um texto ("isso soa como eu?")

1. Salve o texto em `drafts/review-<nome>.md` e rode o `compare`.
2. Leia o perfil e avalie o que o script não mede: ordem dos argumentos, estrutura dos parágrafos, diálogo
   com autores, transições, assertividade.
3. Relate do mais grave ao menos grave. Para cada desvio, mostre o trecho, explique por que destoa (regra ou
   número) e proponha a reescrita.
4. Não altere conteúdo, dados nem referências. Não "corrija" termos técnicos só por serem raros no corpus.

## Calibrar o perfil ("não soou como eu porque...")

1. Para cada observação do autor, encontre a causa no perfil: regra ausente, vaga, errada, ou exemplo ruim.
2. Confira no corpus (`data/`) e em `reports/metrics.md`.
   - Se o corpus confirmar, corrija a regra com a evidência.
   - Se o corpus contradisser, registre em "Notas do autor" no fim de `profile/style.md`: o autor decide
     como quer escrever.
   - Preferências novas ("quero evitar X") entram na lista negra ou nas regras práticas, marcadas como
     "preferência declarada".
3. Reescreva o texto avaliado, salve com sufixo `-v2`, rode o `compare` e mostre ao autor o que mudou no perfil.
