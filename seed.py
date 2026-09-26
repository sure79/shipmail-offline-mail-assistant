"""All seed material is draft, not a specification or user correspondence."""
TERMS = [
('MSBD','주 배전반 후보','약어 확장은 호선 문맥 확인 필요'),('ESBD','비상 배전반 후보','약어 확장은 호선 문맥 확인 필요'),
('ECR','기관 제어실 후보','약어 확장은 문맥 확인 필요'),('ECC','원문 유지 / 확인 필요','제조사 및 호선에 따라 의미가 다를 수 있음'),
('AMS','경보·감시 시스템 후보','약어 확장은 사양 확인 필요'),('POWER DIAGRAM','전원 계통도','도면 명칭 확인'),
('FIRE DETECTION SYSTEM','화재 감지 시스템','프로젝트 사양 확인'),('SPACE HEATER','결로 방지용 히터','용도와 설치 위치 확인'),
('CABLE GLAND','케이블 글랜드','규격 확인'),('CABLE OUTER DIAMETER','케이블 외경','단위 확인'),('STARTER','기동기','회로 문맥 확인'),
('DOL','직입 기동 후보','기동 방식 문맥 확인'),('Y/D','스타-델타 기동 후보','결선 및 기동 방식 확인'),
('SOFT STARTER','소프트 스타터','장비 사양 확인'),('DRAWING REVISION','도면 개정','최신 개정 및 대체 관계 확인')]
EXAMPLES = [
('도면 송부','검토용 도면을 보내드립니다.','Please find the drawing for your review.'),
('도면 송부','수정 도면을 첨부합니다.','Please find the revised drawing attached.'),
('도면 송부','요청하신 자료를 보내드립니다.','Please find the requested information.'),
('도면 송부','최신 도면을 보내주시기 바랍니다.','Please send us the latest drawing.'),
('수정 요청','케이블 외경을 표기해 주시기 바랍니다.','Please indicate the cable outer diameter.'),
('수정 요청','장비 번호를 확인해 주시기 바랍니다.','Please check the equipment number.'),
('수정 요청','변경 부분을 표시해 주시기 바랍니다.','Please mark the changes.'),
('수정 요청','주석을 도면에 반영해 주시기 바랍니다.','Please incorporate the comments into the drawing.'),
('승인 요청','검토 후 승인 부탁드립니다.','Please review and approve the drawing.'),
('승인 요청','승인 여부를 알려주시기 바랍니다.','Please let us know whether it is approved.'),
('승인 요청','추가 의견이 있는지 확인 부탁드립니다.','Please confirm whether you have any further comments.'),
('승인 요청','아직 승인을 받지 못했습니다.','We have not yet received approval.'),
('공급 범위','공급 범위를 확인해 주시기 바랍니다.','Please confirm the scope of supply.'),
('공급 범위','케이블 글랜드가 공급에 포함되는지 확인 부탁드립니다.','Please confirm whether cable glands are included in the supply.'),
('공급 범위','설치 담당 주체를 알려주시기 바랍니다.','Please advise who is responsible for installation.'),
('공급 범위','히터 포함 여부를 확인 부탁드립니다.','Please confirm whether a space heater is included.'),
('전압·용량','정격 전압을 알려주시기 바랍니다.','Please advise the rated voltage.'),
('전압·용량','소비 전력을 확인해 주시기 바랍니다.','Please confirm the power consumption.'),
('전압·용량','기동 전류 자료를 보내주시기 바랍니다.','Please send the starting current data.'),
('전압·용량','전원 사양을 확인해 주시기 바랍니다.','Please confirm the power supply specifications.'),
('기한 확인','회신 가능한 날짜를 알려주시기 바랍니다.','Please let us know when you can reply.'),
('기한 확인','도면 제출 일정을 확인 부탁드립니다.','Please confirm the drawing submission schedule.'),
('기한 확인','납기 확정 여부를 알려주시기 바랍니다.','Please advise whether the delivery date has been confirmed.'),
('기한 확인','일정 변경이 있으면 알려주시기 바랍니다.','Please let us know if the schedule changes.'),
('확인 요청','이 항목의 의미를 설명해 주시기 바랍니다.','Please clarify the meaning of this item.'),
('확인 요청','관련 도면 번호를 알려주시기 바랍니다.','Please advise the relevant drawing number.'),
('확인 요청','첨부파일을 받지 못했습니다.','We did not receive the attachment.'),
('확인 요청','검토 중이며 아직 확정되지 않았습니다.','This is under review and has not yet been finalized.'),
('범위 확인','변경은 해당 장비에만 적용됩니다.','The change applies only to the equipment concerned.'),
('범위 확인','나머지 항목은 변경되지 않았습니다.','The remaining items are unchanged.'),
('회신','회신해 주셔서 감사합니다.','Thank you for your reply.'),
('회신','확인 후 다시 연락드리겠습니다.','We will get back to you after checking.')]

def records():
    for en, ko, context in TERMS:
        yield 'terms', dict(english=en, korean=ko, aliases='', domain='조선 전장', context=context, hull='', source='개발자 작성 후보 · 실제 호선 요구사항 아님', status='draft')
    for purpose, ko, en in EXAMPLES:
        yield 'examples', dict(korean=ko, english=en, purpose=purpose, tags=purpose, source='개발자 작성 초안 · 사용자 실제 메일 아님', status='draft')
