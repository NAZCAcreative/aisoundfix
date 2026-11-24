import json
from pathlib import Path

def test_shared_contract_structure():
    contract_path = Path(__file__).parent.parent.parent / "shared" / "contract.json"
    assert contract_path.exists(), "shared/contract.json must exist"

    with open(contract_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "tiers" in data
    assert "lite" in data["tiers"]
    assert "standard" in data["tiers"]
    assert data["tiers"]["lite"]["stages"] == ["디코딩", "압축 아티팩트 복원", "마스터링", "인코딩"]
    assert data["tiers"]["standard"]["stages"] == ["디코딩", "스템 분리·보컬 개선", "압축 아티팩트 복원", "마스터링", "인코딩"]
    print("Contract test PASSED successfully!")

if __name__ == "__main__":
    test_shared_contract_structure()
