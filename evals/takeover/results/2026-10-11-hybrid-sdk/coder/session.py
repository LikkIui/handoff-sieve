def can_renew(*, age: int, used: bool) -> bool:
    return not used and 0 <= age < 17
