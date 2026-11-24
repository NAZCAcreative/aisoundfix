from .config import Config

class ContractLoader:
    _contract = None

    @classmethod
    def load(cls):
        if cls._contract is None:
            cls._contract = Config.get_contract()
        return cls._contract
