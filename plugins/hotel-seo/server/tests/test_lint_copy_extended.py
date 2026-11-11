"""Extended copy lint (copylint.py): one positive and one negative case per rule."""
from hotel_seo_tools import checks, copylint as cl


def rep(blocks, title='Page', hotel='Atana Hotel', **kw):
    return cl.copy_report({'hotel': hotel, 'sections': [{'number': 'A', 'title': title, 'blocks': blocks, **kw}]},
                          **({'units_pref': kw.pop('units_pref')} if 'units_pref' in kw else {}))


def units(*us, **kw):
    return cl.report_units([{'kind': k, 'text': t, 'where': '/p/'} for k, t in us], **kw)


def has(lines, needle):
    return any(needle in x for x in lines)


# ---------------------------------------------------------------- API kept

def test_lint_copy_still_a_flat_list_with_problems_first():
    doc = {'hotel': 'H', 'sections': [{'number': 'A', 'title': 'x', 'blocks': [
        {'paste': 'Welcome to the hotel. Moreover, it is nestled by the sea.'}]}]}
    out = checks.lint_copy(doc)
    assert isinstance(out, list) and out[0].startswith('A x: stock opening')
    assert any(x.startswith('(warning) A x: AI tell "nestled"') for x in out)
    assert checks.AI_TELLS.search('nestled') and checks.AI_TELLS.search('utilize')


# ---------------------------------------------------------------- 1. title pixels

def test_title_pixel_width():
    wide = 'WWW MMMM WWW MMMM WWW MMMM WWW MMMM WWW MMMM WWW MMMM WW'     # 56 characters
    r = units(('title', wide))
    assert len(wide) <= 62 and has(r['problems'], 'px wide')
    assert r['lengths'][0]['px'] > cl.TITLE_MAX_PX and r['lengths'][0]['count'].startswith('56/60, ')
    ok = units(('title', 'Deluxe King Room with Burj Khalifa View | Gevora Hotel Dubai'))
    assert ok['problems'] == [] and ok['lengths'][0]['px'] <= cl.TITLE_MAX_PX


def test_arabic_title_counts_characters_only():
    r = units(('title', 'فندق عائلي في برشا هايتس مع غرف واسعة ومطبخ صغير | فندق أتانا'))
    assert r['lengths'][0]['px'] is None and 'px' not in r['lengths'][0]['count']


def test_title_char_limit_unchanged():
    long = 'Family Hotel Apartments in Al Barsha near Mall of the Emirates | Abar'
    assert has(units(('title', long))['problems'], f'title is {len(long)} characters (max 62)')


def test_lengths_for_meta_and_alt():
    r = units(('meta', 'A' * 148), ('alt', 'Rooftop pool at Atana Hotel'))
    assert [x['count'] for x in r['lengths']] == ['148/155', '27/125']


# ---------------------------------------------------------------- 2. prices in FAQ answers

def test_faq_answer_price_is_problem():
    for answer in ('Parking costs AED 50 a day.', 'Rooms from 450 per night.', 'Members save 10%.'):
        assert has(units(('faq_answer', answer))['problems'], 'FAQ answer with a price'), answer
    clean = units(('faq_answer', 'Check-in is from 2 pm and check-out is until 12:00.'),
                  ('faq_answer', 'The airport is from 20 minutes away by taxi.'))
    assert not has(clean['problems'], 'price')


def test_faq_in_paste_block_and_table():
    r = rep([{'h3': 'FAQ'}, {'paste': '**Is parking free?**\nParking is AED 30 per day.'}])
    assert has(r['problems'], 'FAQ answer with a price')
    r = rep([{'table': {'columns': ['Question', 'Answer'], 'rows': [['Pool?', 'Yes, from AED 100.']]}}])
    assert has(r['problems'], 'FAQ answer with a price')
    # a price in normal page copy is not an FAQ problem
    assert not has(rep([{'paste': 'The Stay & Splash offer is AED 450 per night.'}])['problems'], 'FAQ')


# ---------------------------------------------------------------- 3. bare pronoun openings

def test_section_starting_with_pronoun_warns():
    r = rep([{'paste': 'Atana Hotel is in Barsha Heights.\n\n## Getting there\n\nIt is a 3-minute walk to the metro.'}])
    assert has(r['warnings'], 'section starts with "It"')
    assert has(rep([{'paste': 'This is the best way to the beach.'}])['warnings'], 'starts with "This"')
    ok = rep([{'paste': 'Atana Hotel is a 3-minute walk from the metro.\n\n## Rooms\n\nThese rooms sleep four.'}])
    assert not has(ok['warnings'], 'section starts with')


# ---------------------------------------------------------------- 4. heading echo

def test_heading_echo_warns():
    r = rep([{'paste': '## Family Suites in Barsha Heights\n\nFamily suites in Barsha Heights are here.'}])
    assert has(r['warnings'], 'repeats its heading')
    r = rep([{'table': {'columns': ['Element', 'Change to'], 'rows': [['H1', 'Rooftop Pool and Gym']]}},
             {'paste': 'The rooftop pool and gym.'}])
    assert has(r['warnings'], 'repeats its heading')
    ok = rep([{'paste': '## Family Suites in Barsha Heights\n\nThe Family Suite at Atana Hotel sleeps two adults and '
                        'two children and has a kitchenette.'}])
    assert not has(ok['warnings'], 'repeats its heading')


# ---------------------------------------------------------------- 5. alt text

def test_alt_text_rules():
    r = units(('alt', 'Image of the rooftop pool at Atana Hotel'), ('alt', 'Lobby ' + 'x' * 130 + ' Atana Hotel'),
              ('alt', 'Twin room with city view'), ('alt', 'Twin room with city view'), hotel_name='Atana Hotel')
    assert has(r['problems'], 'alt text starts "Image of"')
    assert has(r['warnings'], 'alt text is 148 characters')
    assert has(r['warnings'], 'same alt text as')
    assert has(r['warnings'], 'alt text without the hotel name (Atana Hotel)')
    ok = units(('alt', 'Twin room with a view of Sheikh Zayed Road at Atana Hotel'), hotel_name='Atana Hotel')
    assert ok['problems'] == [] and ok['warnings'] == []


# ---------------------------------------------------------------- 6. button text

def test_banned_button_text():
    for b in ('Read more', 'Click here', 'View more', 'Learn more', 'Submit', 'READ MORE →'):
        assert has(units(('button', b))['problems'], 'button text'), b
    assert units(('button', 'View Deluxe King Room'))['problems'] == []
    r = rep([{'note': '**Booking button:** Click here'}])
    assert has(r['problems'], 'button text "Click here"')


# ---------------------------------------------------------------- 7. time-sensitive words

def test_time_sensitive_words_warn_in_copy_only():
    r = rep([{'paste': 'The spa is currently open and the pool was newly opened in 2025.'}])
    assert has(r['warnings'], '"currently" will date') and has(r['warnings'], '"newly opened"') \
        and has(r['warnings'], '"2025"')
    notes = rep([{'p': 'The site currently shows the 2024 rates.'}])        # our note to the agency, not copy
    assert not has(notes['warnings'], 'will date')
    assert not has(rep([{'paste': 'The suite is 2,024 sq ft.'}])['warnings'], 'will date')


# ---------------------------------------------------------------- 8. room sizes

def test_room_size_units():
    assert has(rep([{'paste': 'The suite is 40 m² (430 sq ft).'}])['warnings'], 'both m² and sq ft ("40 m²"')
    assert has(rep([{'paste': 'The suite is 40 m².'}], units_pref='sq ft')['warnings'], "not in this hotel's unit")
    ok = rep([{'paste': 'The suite is 430 sq ft.'}], units_pref='sq ft')
    assert not has(ok['warnings'], 'unit')


# ---------------------------------------------------------------- 9. AI-tell clusters

def test_single_ai_tell_is_warning_only():
    r = rep([{'paste': 'The suite boasts a kitchenette.'}])
    assert has(r['warnings'], 'AI tell "boasts"') and not has(r['problems'], 'AI')


def test_ai_tells_in_three_categories_is_problem():
    r = rep([{'paste': 'Moreover, the suite boasts a kitchenette. Guests utilize the gym.'}])
    assert has(r['problems'], 'reads as AI-written (3 tells in 3 kinds')


def test_six_ai_tells_in_one_category_is_problem():
    r = rep([{'paste': 'A seamless, robust, comprehensive, pivotal, vibrant and bustling stay.'}])
    assert has(r['problems'], 'reads as AI-written (6 tells in 1 kinds')
    five = rep([{'paste': 'A seamless, robust, comprehensive, pivotal and vibrant stay.'}])
    assert not has(five['problems'], 'AI-written')
    assert cl.AI_TELL_PROBLEM_CATEGORIES == 3 and cl.AI_TELL_PROBLEM_HITS == 6


def test_transitions_only_at_sentence_start_and_filler():
    assert has(rep([{'paste': 'The pool is open. Furthermore, the gym is free.'}])['warnings'], 'Furthermore')
    assert not has(rep([{'paste': 'The pool is open and additionally heated.'}])['warnings'], 'additionally')
    assert has(rep([{'paste': 'It is worth noting the pool is heated.'}])['warnings'], 'worth noting')


# ---------------------------------------------------------------- 10. main phrase

def test_main_phrase_missing_and_stuffed():
    blocks = [{'table': {'columns': ['Element', 'Change to'], 'rows': [
        ['Title', 'Rooms | Atana Hotel'], ['H1', 'Family Hotel in Barsha Heights']]}},
        {'paste': 'Atana Hotel has 120 rooms. The gym is open all day. Family hotel barsha heights guests love '
                  'the family hotel barsha heights pool and the family hotel barsha heights kids club.'}]
    r = rep(blocks, main_phrase='family hotel barsha heights')
    assert has(r['warnings'], 'is not in the title') and has(r['warnings'], 'is not in the first two sentences')
    assert not has(r['warnings'], 'is not in the H1')
    assert has(r['warnings'], 'used 3 times in the intro')
    good = rep([{'table': {'columns': ['Element', 'Change to'], 'rows': [
        ['Title', 'Family Hotel in Barsha Heights | Atana Hotel'], ['H1', 'Family Hotel in Barsha Heights']]}},
        {'paste': 'Atana Hotel is a family hotel in Barsha Heights, a 3-minute walk from the metro.'}],
        main_phrase='family hotel barsha heights')
    assert not has(good['warnings'], 'main phrase')
    assert not has(rep(blocks)['warnings'], 'main phrase')               # no phrase given: no check


# ---------------------------------------------------------------- wiring

def test_row_labels_and_quoted_columns():
    r = rep([{'table': {'columns': ['Element', 'Now', 'Change to'], 'rows': [
        ['Title', 'Image of x ' * 10, 'Rooms | Atana Hotel'], ['Alt text', 'Image of a pool', 'Pool at Atana Hotel']]}}])
    assert r['problems'] == [] and [x['unit'] for x in r['lengths']] == ['title', 'alt']

