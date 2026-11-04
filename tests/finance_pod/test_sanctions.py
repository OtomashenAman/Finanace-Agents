from sqlalchemy.ext.asyncio import AsyncSession

from src.app.finance_pod.onboarding import sanctions
from src.app.finance_pod.onboarding.agent import aba_valid

SDN = (
    b'306,"BANCO NACIONAL DE CUBA","-0-","CUBA",-0-,-0-\n'
    b'7140,"ACME TRADING LLC","-0-","SDGT",-0-,-0-\n'
    b"not a row\n"
)


async def test_names_are_screened_after_normalizing_legal_suffixes(db: AsyncSession) -> None:
    assert await sanctions.screen(db, ["Anyone"]) is None  # no list: never a silent pass
    assert await sanctions.load(db, SDN) == 2
    await db.commit()
    [hit] = await sanctions.screen(db, ["Acme Trading, Inc."]) or []
    assert (hit.name, hit.program, hit.list_ref) == ("ACME TRADING LLC", "SDGT", "7140")
    assert await sanctions.screen(db, ["Acme Laboratories"]) == []


def test_routing_numbers_are_checked_with_the_aba_checksum() -> None:
    assert aba_valid("021000021")
    assert not aba_valid("021000022")
    assert not aba_valid("12345")
