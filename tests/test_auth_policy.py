"""Unit tests for SchemaSense authentication policy, environment guards,
and local-operator evaluation opt-in safeguards.
"""

from __future__ import annotations

from schemasense.auth import is_local_evaluation_permitted, is_production_environment


class TestProductionEnvironmentDetection:
    """Verifies fail-closed production environment classification."""

    def test_production_default_is_false_when_unset(self, monkeypatch):
        monkeypatch.delenv("SCHEMASENSE_ENV", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        assert is_production_environment() is False

    def test_production_detected_via_schemasense_env(self, monkeypatch):
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        for token in ("production", "prod", "Production", "PROD", "  prod  "):
            monkeypatch.setenv("SCHEMASENSE_ENV", token)
            assert is_production_environment() is True, f"Failed for token: {token}"

    def test_production_detected_via_environment_var(self, monkeypatch):
        monkeypatch.delenv("SCHEMASENSE_ENV", raising=False)
        for token in ("production", "prod", "PRODUCTION", "pRoD"):
            monkeypatch.setenv("ENVIRONMENT", token)
            assert is_production_environment() is True, f"Failed for token: {token}"

    def test_conflicting_environments_resolve_safely_to_production(self, monkeypatch):
        # Development in one variable cannot override production in the other
        monkeypatch.setenv("SCHEMASENSE_ENV", "development")
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert is_production_environment() is True

        monkeypatch.setenv("SCHEMASENSE_ENV", "prod")
        monkeypatch.setenv("ENVIRONMENT", "development")
        assert is_production_environment() is True

        monkeypatch.setenv("SCHEMASENSE_ENV", "staging")
        monkeypatch.setenv("ENVIRONMENT", "PRODUCTION")
        assert is_production_environment() is True

    def test_non_production_environments_return_false(self, monkeypatch):
        for env in ("development", "dev", "staging", "test", "local", "ci", ""):
            monkeypatch.setenv("SCHEMASENSE_ENV", env)
            monkeypatch.setenv("ENVIRONMENT", env)
            assert is_production_environment() is False, f"Failed for env: {env}"


class TestLocalEvaluationPermissionPolicy:
    """Verifies that local evaluation requires explicit opt-in and fails closed."""

    def test_evaluation_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("SCHEMASENSE_ENABLE_LOCAL_EVALUATION", raising=False)
        monkeypatch.delenv("SCHEMASENSE_ENV", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("SCHEMASENSE_ACCESS_KEY", raising=False)
        assert is_local_evaluation_permitted() is False

    def test_explicitly_enabled_in_development(self, monkeypatch):
        monkeypatch.delenv("SCHEMASENSE_ACCESS_KEY", raising=False)
        monkeypatch.delenv("SCHEMASENSE_REQUIRE_AUTH", raising=False)
        monkeypatch.setenv("SCHEMASENSE_ENV", "development")

        for token in ("true", "1", "yes", "True", "TRUE", "  yes  "):
            monkeypatch.setenv("SCHEMASENSE_ENABLE_LOCAL_EVALUATION", token)
            assert is_local_evaluation_permitted() is True, f"Failed for token: {token}"

    def test_explicitly_disabled_despite_development_environment(self, monkeypatch):
        monkeypatch.setenv("SCHEMASENSE_ENV", "development")
        monkeypatch.delenv("SCHEMASENSE_ACCESS_KEY", raising=False)

        for token in ("false", "0", "no", "False", "none", "off", "disabled"):
            monkeypatch.setenv("SCHEMASENSE_ENABLE_LOCAL_EVALUATION", token)
            assert is_local_evaluation_permitted() is False, (
                f"Failed for token: {token}"
            )

    def test_invalid_and_ambiguous_opt_in_values_fail_closed(self, monkeypatch):
        monkeypatch.setenv("SCHEMASENSE_ENV", "development")
        monkeypatch.delenv("SCHEMASENSE_ACCESS_KEY", raising=False)

        for invalid in ("maybe", "2", "truee", "yess", "enable", "on", "sure", "-1"):
            monkeypatch.setenv("SCHEMASENSE_ENABLE_LOCAL_EVALUATION", invalid)
            assert is_local_evaluation_permitted() is False, f"Failed for: {invalid}"

    def test_production_cannot_be_overridden_by_evaluation_opt_in(self, monkeypatch):
        monkeypatch.setenv("SCHEMASENSE_ENABLE_LOCAL_EVALUATION", "true")
        monkeypatch.delenv("SCHEMASENSE_ACCESS_KEY", raising=False)

        # Both SCHEMASENSE_ENV and ENVIRONMENT must block
        monkeypatch.setenv("SCHEMASENSE_ENV", "production")
        assert is_local_evaluation_permitted() is False

        monkeypatch.setenv("SCHEMASENSE_ENV", "prod")
        assert is_local_evaluation_permitted() is False

        monkeypatch.delenv("SCHEMASENSE_ENV", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert is_local_evaluation_permitted() is False

        # Conflicting settings: development cannot override production
        monkeypatch.setenv("SCHEMASENSE_ENV", "development")
        monkeypatch.setenv("ENVIRONMENT", "prod")
        assert is_local_evaluation_permitted() is False

    def test_access_key_cannot_be_bypassed_by_evaluation_mode(self, monkeypatch):
        """A configured SCHEMASENSE_ACCESS_KEY requires key authentication and disables bypass."""
        monkeypatch.setenv("SCHEMASENSE_ENABLE_LOCAL_EVALUATION", "true")
        monkeypatch.setenv("SCHEMASENSE_ENV", "development")

        monkeypatch.setenv("SCHEMASENSE_ACCESS_KEY", "super-secret-key-1234")
        assert is_local_evaluation_permitted() is False

        monkeypatch.delenv("SCHEMASENSE_ACCESS_KEY", raising=False)
        monkeypatch.setenv("SCHEMASENSE_AUTH_KEY", "fallback-secret-key")
        assert is_local_evaluation_permitted() is False

    def test_mandatory_auth_cannot_be_bypassed(self, monkeypatch):
        monkeypatch.setenv("SCHEMASENSE_ENABLE_LOCAL_EVALUATION", "true")
        monkeypatch.setenv("SCHEMASENSE_ENV", "development")
        monkeypatch.delenv("SCHEMASENSE_ACCESS_KEY", raising=False)

        for val in ("true", "1", "yes", True):
            monkeypatch.setenv("SCHEMASENSE_REQUIRE_AUTH", str(val))
            assert is_local_evaluation_permitted() is False

    def test_direct_parameter_calls(self):
        # Testing pure function calls without os.environ dependency
        assert (
            is_local_evaluation_permitted(
                enable_eval=True, schemasense_env="development"
            )
            is True
        )
        assert (
            is_local_evaluation_permitted(
                enable_eval=False, schemasense_env="development"
            )
            is False
        )
        assert (
            is_local_evaluation_permitted(
                enable_eval="true", schemasense_env="production"
            )
            is False
        )
        assert (
            is_local_evaluation_permitted(enable_eval="true", access_key="token-abc")
            is False
        )
        assert (
            is_local_evaluation_permitted(enable_eval="true", require_auth=True)
            is False
        )
