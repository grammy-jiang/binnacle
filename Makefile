UV := uv

.PHONY: verify verify-python verify-quality

# Canonical clean-checkout and pre-push verification profile. Keep these commands
# aligned with spec/acceptance/phase10-policy.json.
verify:
	$(UV) run tox run -e py311
	$(UV) run tox run -e py312
	$(UV) run tox run -e py313
	$(UV) run tox run -e quality
	$(UV) run pre-commit run --all-files

# Narrow entry point for one supported Python version.
verify-python:
	@case "$(PYTHON)" in \
		3.11) tox_env=py311 ;; \
		3.12) tox_env=py312 ;; \
		3.13) tox_env=py313 ;; \
		*) echo "verify-python: PYTHON must be one of 3.11, 3.12, or 3.13 (got '$(PYTHON)')" >&2; exit 2 ;; \
	esac; \
	$(UV) run tox run -e "$$tox_env"

# Narrow entry point for every non-matrix check, including repository/security hooks.
verify-quality:
	$(UV) run tox run -e quality
	$(UV) run pre-commit run --all-files
