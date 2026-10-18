from chipxray.bench import rules_run, score, summarize


def test_score_maps_aliases_back():
    from chipxray.facts import alias_map
    a = alias_map("blobs/espressif/esp32s3_librftest.a")
    s = score("esp32s3", True, [a["esp_phy_wifi_tx"], a["adctrig"]])
    assert s["adctrig_pos"] == 2 and s["neg_in_top10"] == 1


def test_rules_and_summary():
    rows = [rules_run("esp32s3", False), rules_run("esp32s3", True)]
    assert rows[0]["adctrig_pos"] == rows[1]["adctrig_pos"]  # rules are name-blind
    assert "| rules | normal | esp32s3 |" in summarize(rows)


if __name__ == "__main__":
    test_score_maps_aliases_back(); test_rules_and_summary(); print("ok")
