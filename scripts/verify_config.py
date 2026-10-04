"""
Verification script for Task 1.1: config.yaml parsing and schema validation.
"""

from pathlib import Path
import sys
import yaml

def verify_config():
    root_dir = Path(__file__).resolve().parent.parent
    config_path = root_dir / "config.yaml"
    
    print("=" * 60)
    print("  VERIFYING TASK 1.1: tracker/ scaffolding and config.yaml")
    print("=" * 60)
    
    # 1. Check file existence
    if not config_path.exists():
        print(f"[FAIL] config.yaml not found at {config_path}")
        sys.exit(1)
    print(f"[OK] Located config.yaml at: {config_path}")
    
    # 2. Parse YAML
    with open(config_path, "r", encoding="utf-8") as f:
        try:
            cfg = yaml.safe_load(f)
        except Exception as e:
            print(f"[FAIL] Failed to parse YAML: {e}")
            sys.exit(1)
    print("[OK] Successfully parsed config.yaml.")
    
    # 3. Verify PDF Requirement 3 mandatory fields
    required_fields = ["topic", "K", "model", "instructions", "tools", "limits", "network"]
    for field in required_fields:
        assert field in cfg, f"Missing required field in config.yaml: '{field}'"
        print(f"  -> Verified field: '{field}' present.")
        
    # 4. Check K constraint: 3 <= K <= 10
    k = cfg.get("K")
    assert isinstance(k, int) and 3 <= k <= 10, f"K must be integer between 3 and 10, got {k}"
    print(f"[OK] K={k} satisfies 3 <= K <= 10.")
    
    # 5. Check tools list
    tools = cfg.get("tools", [])
    expected_tools = {"search_web", "fetch_article", "finish"}
    assert expected_tools.issubset(set(tools)), f"Tools must include {expected_tools}, got {tools}"
    print(f"[OK] Tools defined: {tools}")
    
    # 6. Check limits
    limits = cfg.get("limits", {})
    for lim in ["max_steps", "max_fetches", "token_budget"]:
        assert lim in limits and limits[lim] > 0, f"Limit '{lim}' must be > 0"
    print(f"[OK] Limits validated: {limits}")
    
    # 7. Check network allowed schemes & hosts
    network = cfg.get("network", {})
    assert "allowed_schemes" in network and "http" in network["allowed_schemes"]
    assert "allowed_hosts" in network
    print(f"[OK] Network guardrails policy validated: {network['allowed_schemes']}")
    
    # 8. Check tracker module
    tracker_init = root_dir / "tracker" / "__init__.py"
    assert tracker_init.exists(), "tracker/__init__.py not found"
    print(f"[OK] Tracker package structure initialized at: {root_dir / 'tracker'}")
    
    print("\n" + "=" * 60)
    print("  TASK 1.1 VERIFICATION SUCCEEDED WITH 100% SUCCESS! ")
    print("=" * 60)

if __name__ == "__main__":
    verify_config()
