.PHONY: help setup pull status prs contratos

help:
	@echo "make setup      baixa todos os repositórios em repos/ (os que já existem são mantidos)"
	@echo "make pull       atualiza todos (fast-forward da branch atual)"
	@echo "make status     branch, arquivos sujos e divergência de cada repo"
	@echo "make prs        PRs abertos em todos"
	@echo "make contratos  confere o acoplamento por SSM entre os repos"

setup:
	@bin/ws clone

pull:
	@bin/ws pull

status:
	@bin/ws status

prs:
	@bin/ws prs

contratos:
	@bin/check-contracts.py
