.PHONY: install run

install:
	python -m pip install -r requirements.txt

run:
	python -m ocd_fetcher --config config.yaml --outdir . --max 200
