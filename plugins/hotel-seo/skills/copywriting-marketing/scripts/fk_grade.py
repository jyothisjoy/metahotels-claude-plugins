"""Flesch-Kincaid grade level for a text file or stdin.

Usage:  python -I fk_grade.py draft.txt        (or pipe text in)
Prints: words, sentences, avg sentence length, FK grade, and the 5 longest
sentences (the usual culprits). Strips HTML tags first, so copy-ready
.html drafts can be checked directly. Syllables are a heuristic count;
treat the grade as +/- 0.5.
"""
import re
import sys


def syllables(word):
    w = word.lower()
    w = re.sub(r"[^a-z]", "", w)
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    groups = re.findall(r"[aeiouy]{1,2}", w)
    return max(1, len(groups))


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>|</div>", ". ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    sentences = [s.strip() for s in re.split(r"[.!?]+(?:\s|$)|\n\s*\n", text) if re.search(r"[A-Za-z]", s)]
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
    if not words or not sentences:
        print("No English text found.")
        return
    syl = sum(syllables(w) for w in words)
    wps = len(words) / len(sentences)
    grade = 0.39 * wps + 11.8 * (syl / len(words)) - 15.59
    print(f"words={len(words)} sentences={len(sentences)} avg_words_per_sentence={wps:.1f}")
    print(f"FK_grade={grade:.1f}  (target < 7.5)")
    longest = sorted(sentences, key=lambda s: len(s.split()), reverse=True)[:5]
    print("Longest sentences:")
    for s in longest:
        print(f"  [{len(s.split())}w] {s[:140]}")


if __name__ == "__main__":
    main()
