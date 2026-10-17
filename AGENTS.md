# AGENTS.md

Instruções para agentes (e pessoas) que alteram o investsh. Uso e formato dos dados estão no
[README](README.md) e em [docs/DATA_FORMAT.md](docs/DATA_FORMAT.md).

## Testes

```bash
.venv/bin/pytest          # rápidos (~10s)
.venv/bin/pytest --all    # tudo, inclusive a TUI (~1 min); é o que o CI roda
```

Rode `--all` antes de commitar mudanças em `src/`. Golden files ficam em `tests/golden/`;
detalhes em [tests/README.md](tests/README.md).

## Versões e releases

Versionamento semântico, com a versão em `__version__` no `src/investsh/__init__.py`:

- **patch**: correção de bug;
- **minor**: funcionalidade ou mudança compatível;
- **major**: mudança incompatível (formato de dados que arquivos antigos não carregam, opção removida).

Toda mudança de comportamento em `src/` sobe a versão no mesmo commit (ou antes do push).
Mudanças só em documentação ou testes não sobem.

Toda versão publicada ganha tag anotada e release no GitHub, com notas em português
(Correções / Novidades / Atualizar com `pipx upgrade investsh`):

```bash
git tag -a vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z
gh release create vX.Y.Z --verify-tag --title vX.Y.Z --notes "..."
```

Sem a mudança de versão, `pipx upgrade investsh` não instala os commits novos.

## Convenções

- Um ativo é identificado por **nome + corretora** (`asset_key` em `src/investsh/core.py`),
  nunca só pelo nome.
- Textos da interface, comentários e documentação em português; mensagens de commit em inglês.
- Dados reais do usuário ficam fora deste repositório (`~/.investsh` por padrão); commits
  de dados lá não sobem versão.
