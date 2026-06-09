

tests:
	pytest

package:
	python setup.py sdist

# Install Web UI backend (Python) + frontend (Node) dependencies.
# Equivalent to running `donkey installweb` against the in-tree web_ui/.
installweb:
	donkey installweb --path ./web_ui

