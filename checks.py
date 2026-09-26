"""Conservative, position-preserving review aids; never proof of equivalence."""
import re
import unicodedata
from collections import Counter

def segments(text):
    # Protect decimals, equipment numbers, revisions and common abbreviations.
    protected = set()
    for m in re.finditer(r'\d\.\d|\b(?:No|Rev|Dr|Mr|Ms|e\.g|i\.e)\.', text, re.I):
        protected.update(i for i in range(m.start(), m.end()) if text[i] == '.')
    spans, start = [], 0
    for i, char in enumerate(text):
        if char == '\n' or (char in '.!?' and i not in protected and (i+1 == len(text) or text[i+1].isspace())):
            end = i+1
            if text[start:end].strip():
                spans.append({'id': len(spans)+1, 'start': start, 'end': end, 'text': text[start:end]})
            start = end
    if text[start:].strip():
        spans.append({'id': len(spans)+1, 'start': start, 'end': len(text), 'text': text[start:]})
    return spans

WEEKDAYS = {name: f'weekday{i}' for i, names in enumerate([('monday', '월요일'), ('tuesday', '화요일'), ('wednesday', '수요일'), ('thursday', '목요일'), ('friday', '금요일'), ('saturday', '토요일'), ('sunday', '일요일')], 1) for name in names}
PATTERN = re.compile(r'\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b|[월화수목금토일]요일|\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b|\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\bNo\.?\s*\d+|\bRev\.?\s*[A-Z0-9]+|\b\d+(?:\.\d+)?\s*(?:kW|kVA|mm|Hz|VAC|VDC|V|A|pcs?|sets?)(?![A-Za-z0-9])|\d+(?:\.\d+)?\s*(?:개|대|세트)|\b[A-Z]+[A-Z0-9]*(?:[-_/][A-Z0-9]+)+\b|\b[A-Z]{1,6}\d+[A-Z0-9]*\b|\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\b|(?<![\w.])\d+(?:\.\d+)?(?![\w.])', re.I)
WORDS = dict(zip('one two three four five six seven eight nine ten'.split(), map(str, range(1, 11))))
REVIEW = re.compile(r'\b(?:not|no(?!\.?\s*\d)|shall|must|required|except|unless|only|if|whether|each|per|by|before|after|supplied|installed|supersedes?|approved|approval)\b|않|없|아니|제외|경우|만(?=[\s,.]|$)|각각|마다|해야|이전|이후|까지|공급|설치|승인|대체', re.I)

def normalize_term(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())

def canonical(value):
    value = unicodedata.normalize('NFKC', value).lower().strip()
    if value in WORDS:
        return WORDS[value]
    if value in WEEKDAYS:
        return WEEKDAYS[value]
    date = re.fullmatch(r'(\d{4})(?:[-/.]|년\s*)(\d{1,2})(?:[-/.]|월\s*)(\d{1,2})일?', value)
    if date:
        return '-'.join(str(int(x)) for x in date.groups())
    value = re.sub(r'\s+', '', value)
    value = re.sub(r'^(no|rev)\.', r'\1', value)
    return re.sub(r'(?:pcs?|sets?|개|대|세트)$', '', value)

# Fixed email formulas are translated by rule so the model never sees them (faster, and no "(이름 한글 음역)"/"최고의 인사로").
FORMULAS = [
    (re.compile(r'^dear\s+(?:sir|sirs|madam|sir\s*/\s*madam|sir\s+or\s+madam|all|team|colleagues)\s*[,.:]?$', re.I), '담당자님께,'),
    (re.compile(r'^(?:dear|hi|hello)\s+((?:mr|ms|mrs|miss|dr|capt)\.?\s+[A-Za-z][A-Za-z .\'-]{0,40}?)\s*[,.:]?$', re.I), None),
    (re.compile(r'^(?:good\s+(?:day|morning|afternoon|evening)|hello|hi|greetings)\s*[,.!]?$', re.I), '안녕하세요.'),
    (re.compile(r'^(?:best|kind|warm|with\s+best|with\s+kind)?\s*regards\s*[,.]?$|^(?:yours\s+)?(?:sincerely|faithfully|truly)(?:\s+yours)?\s*[,.]?$|^best\s+wishes\s*[,.]?$|^(?:many\s+)?thanks\s*(?:and|&)\s*(?:best\s+)?regards\s*[,.]?$', re.I), '감사합니다. (맺음말)'),
    (re.compile(r'^thank\s+you(?:\s+(?:very|so)\s+much)?(?:\s+for\s+your\s+(?:cooperation|co-operation|support|kind\s+cooperation))?\s*[,.!]?$', re.I), '협조에 감사드립니다.'),
    (re.compile(r'^thanks?(?:\s+in\s+advance)?\s*[,.!]?$', re.I), '감사합니다.'),
]
CLOSING = FORMULAS[3][0]

def formula_korean(text):
    line = ' '.join(text.split())
    for pattern, korean in FORMULAS:
        m = pattern.match(line)
        if m:
            return korean if korean is not None else f'{m.group(1)} 님께,'
    return None

def rule_translations(segs):
    """Return {segment id: korean} for greeting/closing formulas and the signature block after a closing line."""
    out, signature = {}, False
    for seg in segs:
        line = ' '.join(seg['text'].split())
        korean = formula_korean(line)
        if korean is not None:
            out[seg['id']] = korean
            signature = bool(CLOSING.match(line))
            continue
        # Signature lines (name, title, company, phone) are kept as written, never translated or transliterated.
        if signature and len(line) <= 60 and not re.search(r'[?]|\b(?:please|could|would|will|shall|must)\b', line, re.I):
            out[seg['id']] = line + '  (서명: 원문 유지)'
            continue
        signature = False
    return out

def extract(text):
    return [{'value': m.group(), 'key': canonical(m.group()), 'start': m.start(), 'end': m.end()} for m in PATTERN.finditer(text)]

# Meaning-limiting concepts that must survive translation in either direction (Korean <-> English).
CONCEPTS = [
    ('범위 한정(만/only)', re.compile(r'(?<=[가-힣A-Za-z0-9])만(?=[\s,.은는이가을를에도]|$)|뿐|\bonly\b|\bsolely\b|\bexclusively\b', re.I)),
    ('예외(제외/except)', re.compile(r'제외|빼고|외에는|\bexcept\b|\bother than\b|\bexcluding\b|\bapart from\b|\bunless\b', re.I)),
    ('부정(않/없/not)', re.compile(r'않|없|아니(?!면)|못|\bnot\b|n\'t\b|\bno\b(?!\.?\s*\d)|\bnever\b|\bnone\b|\bwithout\b|\bunchanged\b', re.I)),
    ('각각·마다(each/per)', re.compile(r'마다|각각|각\s|당\s|\beach\b|\bper\b|\bevery\b', re.I)),
    ('조건(경우/if)', re.compile(r'경우|한해|한하여|조건|다면|라면|으면|\bif\b|\bunless\b|\bprovided that\b|\bon condition\b|\bin case\b', re.I)),
]

def concept_gaps(source, target):
    gaps = []
    for name, pattern in CONCEPTS:
        src, dst = pattern.search(source), pattern.search(target)
        if src and not dst:
            gaps.append({'concept': name, 'side': 'missing', 'value': src.group(), 'start': src.start(), 'end': src.end()})
        elif dst and not src:
            gaps.append({'concept': name, 'side': 'added', 'value': dst.group(), 'start': dst.start(), 'end': dst.end()})
    return gaps

def compare(source, target):
    left, right = extract(source), extract(target)
    counts = Counter(x['key'] for x in right)
    missing = []
    for item in left:
        if counts[item['key']]:
            counts[item['key']] -= 1
        else:
            missing.append(item)
    counts = Counter(x['key'] for x in left)
    added = []
    for item in right:
        if counts[item['key']]:
            counts[item['key']] -= 1
        else:
            added.append(item)
    return {'missing': missing, 'added': added, 'concept_gaps': concept_gaps(source, target) if source.strip() and target.strip() else [], 'source_markers': [{'value': m.group(), 'start': m.start(), 'end': m.end()} for m in REVIEW.finditer(source)], 'target_markers': [{'value': m.group(), 'start': m.start(), 'end': m.end()} for m in REVIEW.finditer(target)], 'notice': '확인 필요: 숫자·표기 및 부정·의무·조건을 사람이 검토하세요. 차이가 없어도 의미 일치를 보장하지 않습니다.'}

# Phrases whose Korean meaning is easy to invert. Shown beside the sentence and passed to the model as hints;
# the translation itself is never altered automatically.
CAUTIONS = [
    (r'\b(?:is|are|be|being|was|were)\s+not\s+required\s+to\b', "'not required to' = ~할 의무 없음 (해도 되고 안 해도 됨). '~하면 안 됨'이 아님"),
    (r'\brequired\s+not\s+to\b', "'required not to' = ~하면 안 됨 (금지). '~할 필요 없음'이 아님"),
    (r'\bneeds?\s+not\b|\bdo(?:es)?\s+not\s+need\s+to\b|\bnot\s+necessary\b', "~할 필요 없음 (금지 아님)"),
    (r'\b(?:must|shall)\s+not\b', "~하면 안 됨 (금지)"),
    (r'\bnot\s+necessarily\b', "반드시 ~인 것은 아님 (부분 부정)"),
    (r'\bexcept\b|\bother\s+than\b|\bexcluding\b', "예외 있음: 제외 대상 확인"),
    (r'\bunless\b', "unless = ~하지 않는 한 (조건)"),
    (r'\bprovided\s+that\b|\bon\s+condition\s+that\b', "조건부: 조건이 충족될 때만"),
    (r'\bfor\s+each\b|\beach\b|\bper\b', "each/per = ~마다·각각 (전체 수량 아님)"),
    (r'\bsupersedes?\b|\breplaces?\b', "대체 방향 확인: 앞의 것이 뒤의 것을 대체"),
    (r'\bwhether\b', "whether = ~인지 여부를 묻는 질문 (확정 사항 아님)"),
    (r'\battach(?:ed|ment)s?\b|\benclosed\b', "첨부 언급: 앱은 첨부 내용을 볼 수 없음"),
]
CAUTION_PATTERNS = [(re.compile(p, re.I), note) for p, note in CAUTIONS]

def cautions(text):
    return [note for pattern, note in CAUTION_PATTERNS if pattern.search(text)]
