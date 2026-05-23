from __future__ import annotations

try:
    from private_bootstrap_eval_corpus import main
except ModuleNotFoundError:
    from evals.private_bootstrap_eval_corpus import main


if __name__ == "__main__":
    main()
