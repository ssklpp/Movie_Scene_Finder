from eval.variants import IndexVariant, char_bigrams, plot_text, scene_caption, tokenizer_for


def test_char_bigrams_per_word_lowercase() -> None:
    assert char_bigrams("초록색 괴물 a Big") == ["초록", "록색", "괴물", "a", "bi", "ig"]


def test_scene_caption_by_language() -> None:
    assert scene_caption("ko", "한국어 캡션", "English caption") == "한국어 캡션"
    assert scene_caption("en", "한국어 캡션", "English caption") == "English caption"
    assert scene_caption("both", "한국어 캡션", "English caption") == "한국어 캡션\nEnglish caption"
    # 영어 캡션이 없으면 한국어로 대신한다
    assert scene_caption("en", "한국어 캡션", None) == "한국어 캡션"


def test_variant_collection_names() -> None:
    v = IndexVariant(doc_lang="en", tokenizer="char2", embed_dim=512)
    assert v.scenes_collection == "exp_en_char2_512_scenes"
    assert v.movies_collection == "exp_en_char2_512_movies"
    assert IndexVariant().name == "exp_ko_kiwi_dict_1536"
    assert IndexVariant(doc_lang="both", plot_doc="plot_kw").name == "exp_both_kiwi_dict_1536_kw"


def test_tokenizer_for_char2_matches_char_bigrams() -> None:
    assert tokenizer_for("char2")("숲속 오두막") == char_bigrams("숲속 오두막")


def test_plot_text_appends_keywords_only_for_plot_kw() -> None:
    assert plot_text("plot", "줄거리", ["양궁", "한강"]) == "줄거리"
    assert plot_text("plot_kw", "줄거리", ["양궁", "한강"]) == "줄거리\n양궁, 한강"
    assert plot_text("plot_kw", "줄거리", None) == "줄거리"
    # 줄거리가 없어도 키워드가 있으면 문서가 된다
    assert plot_text("plot_kw", None, ["양궁"]) == "양궁"
    assert plot_text("plot", None, ["양궁"]) == ""
