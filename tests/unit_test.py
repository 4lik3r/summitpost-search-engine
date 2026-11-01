# test_fields                - all 11 fields (name, country, ..., score) of all 22 pages match the values checked by hand
# test_description_start     - the description is the right chapter (Intro/Overview), e.g. Krivan skips "What's new"
# test_description_is_clean  - the description is plain ASCII text, no html tags, no &# entities, no tabs or newlines
# test_coordinates_sign      - S and W coordinates are negative, N and E are positive
# test_clean                 - special characters are changed to ASCII (Kriva&#328; -> Krivan, Großer -> Grosser, ...)

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from extractor import clean, extract

# folder with the test pages (from the project folder), change it here if the pages are somewhere else
PAGES = "tests/pages"

FIELDS = ["name", "country", "continent", "region", "lat", "lon", "elevation_m",
          "activities", "season", "parent", "score"]

# id: (name, country, continent, region, lat, lon, elevation_m, activities, season, parent, score)
EXPECTED = {
    "150191": ("Wheeler Peak", "United States", "North America", "Nevada", "38.98603", "-114.31327", "3982",
               "Hiking, Mountaineering", "Spring, Fall, Winter", "Great Basin National Park", "98.62"),
    "150192": ("Pico de Orizaba", "Mexico", "North America", "Puebla", "19.03024", "-97.26814", "5636",
               "Hiking, Mountaineering, Scrambling", "Winter", "Mexican Volcanoes", "99.87"),
    "150193": ("Iztaccihuatl", "Mexico", "North America", "Puebla", "19.17860", "-98.64188", "5230",
               "Mountaineering", "", "Mexican Volcanoes", "99.41"),
    "150197": ("Aconcagua", "Argentina", "South America", "Mendoza", "-32.65335", "-70.01149", "6962",
               "", "", "Aconcagua Group", "100"),
    "150199": ("Denali", "United States", "North America", "Alaska", "63.06909", "-151.00708", "6194",
               "Mountaineering, Ice Climbing, Mixed, Skiing", "Spring, Summer, Fall, Winter", "Alaska Range", "99.99"),
    "150202": ("Kilimanjaro", "Tanzania", "Africa", "", "-3.07645", "37.35403", "5896",
               "", "", "Seven Summits", "99.68"),
    "150227": ("Mount Whitney", "United States", "North America", "California", "36.57860", "-118.293", "4421",
               "", "", "John Muir Wilderness", "100"),
    "150230": ("Everest", "China/Nepal", "Asia", "Tibet/Khumbu", "27.98818", "86.92457", "8849",
               "", "", "The Top 10", "100"),
    "150235": ("Matterhorn - Monte Cervino", "Italy/Switzerland", "Europe", "Valais", "45.97627", "7.65738", "4478",
               "Mountaineering", "", "Pennine Alps", "99.99"),
    "150245": ("Mont Blanc/Monte Bianco", "France/Italy", "Europe", "Mont Blanc massif/Haute Savoie/Valle d'Aosta",
               "45.83330", "6.86422", "4810", "Mountaineering, Trad Climbing, Ice Climbing, Mixed, Skiing",
               "Summer", "Mont Blanc GROUP", "99.94"),
    "150257": ("K2", "China/Pakistan", "Asia", "", "35.88034", "76.51246", "8611",
               "", "", "The Karakoram", "70.48"),
    "150306": ("Aoraki - Cook", "New Zealand", "Australia/Oceana", "Canterbury", "-43.6", "170.14999", "3754",
               "", "", "Southern Alps", "98.35"),
    "150310": ("Longs Peak", "United States", "North America", "Colorado", "40.25470", "-105.6153", "4346",
               "", "", "Glacier Gorge", "99.85"),
    "150324": ("Popocatepetl", "Mexico", "North America", "Puebla", "19.02240", "-98.6279", "5452",
               "Mountaineering", "Winter", "Mexican Volcanoes", "95.86"),
    "150343": ("Rysy", "Poland/Slovakia", "Europe", "Tatra Mountains", "49.18330", "20.08330", "2503",
               "", "", "High Tatras / Vysoke Tatry", "97.89"),
    "150749": ("Gerlachovsky Stit", "Slovakia", "Europe", "Vysoke Tatry", "49.15000", "20.08330", "2655",
               "", "", "High Tatras / Vysoke Tatry", "94.82"),
    "150792": ("Galdhopiggen", "Norway", "Europe", "Oppland", "61.63720", "8.31167", "2469",
               "Hiking, Mountaineering", "Spring, Summer, Fall, Winter", "Jotunheimen", "95.69"),
    "151399": ("Bettelwurf, Grosser", "Austria", "Europe", "Tyrol", "47.34487", "11.51505", "2725",
               "", "", "Karwendel", "76.82"),
    "153012": ("Pu'u Koa'e (Puu Koae, Sugarloaf)", "United States", "--", "Hawaii", "21.00109", "-156.54536", "194",
               "", "", "Maui Peaks", "82.27"),
    "154957": ("Krivan", "Slovakia", "Europe", "Vysoke Tatry", "49.16274", "20.00010", "2494",
               "Hiking, Mountaineering, Trad Climbing, Toprope, Ice Climbing, Mixed, Scrambling, Skiing",
               "Spring, Summer, Fall, Winter", "High Tatras / Vysoke Tatry", "93.23"),
    "173204": ("Deravica / Gjeravica", "Serbia", "Europe", "Kosovo", "42.53280", "20.14030", "2656",
               "Hiking, Mountaineering, Scrambling", "Spring, Summer, Fall, Winter", "Prokletije", "92.73"),
    "424291": ("Wolowiec (Volovec)", "Poland/Slovakia", "Europe", "MaloPoslka / Liptov", "49.21513", "19.75788", "2063",
               "Hiking, Mountaineering", "Spring, Summer, Fall, Winter", "Western Tatras (Zapadne Tatry / Tatry Zachodnie)",
               "82.32"),
}

# how the description (Intro / Overview / chapter 1) has to start
DESCRIPTION_START = {
    "150191": "Wheeler Peak is located in Great Basin National Park",
    "150192": "El Pico de Orizaba (known as Citlaltepetl",
    "150197": "Aconcagua is the highest mountain in the Western hemisphere",
    "150199": "Formerly known as Mount McKinley",
    "150230": '"Chomolungma or Qomolangma" to Tibetans',
    "150306": "Mount Cook, the highest mountain in New Zealand",
    "150343": "Rysy ,Meeraugspitze ,Tengerszem-csucs 2503",
    "154957": "Krivan (slo), Krywan (pol)",  # chapter 1 is "What's new on the page???", we want "Overview"
}


def load(page_id):
    with open(os.path.join(PAGES, page_id + ".html"), encoding="utf-8") as f:
        return extract(page_id, f.read())


class TestExtractor(unittest.TestCase):

    # every field of every page has the value we checked by hand
    def test_fields(self):
        self.assertGreaterEqual(len(EXPECTED), 20)
        for page_id, values in EXPECTED.items():
            row = load(page_id)
            for field, value in zip(FIELDS, values):
                with self.subTest(page=page_id, field=field):
                    self.assertEqual(row[field], value)

    # the description is the right chapter
    def test_description_start(self):
        for page_id, start in DESCRIPTION_START.items():
            with self.subTest(page=page_id):
                self.assertTrue(load(page_id)["description"].startswith(start))

    # the description is only plain text: no html, no entities, no tabs/newlines (would break the TSV), only ASCII
    def test_description_is_clean(self):
        for page_id in EXPECTED:
            description = load(page_id)["description"]
            with self.subTest(page=page_id):
                self.assertTrue(description)
                self.assertNotIn("<", description)
                self.assertNotIn("&#", description)
                self.assertNotIn("\t", description)
                self.assertNotIn("\n", description)
                self.assertTrue(description.isascii())

    # S and W coordinates are negative, N and E positive
    def test_coordinates_sign(self):
        self.assertTrue(load("150197")["lat"].startswith("-"))      # Aconcagua, S
        self.assertTrue(load("150197")["lon"].startswith("-"))      # Aconcagua, W
        self.assertFalse(load("150230")["lat"].startswith("-"))     # Everest, N
        self.assertFalse(load("150230")["lon"].startswith("-"))     # Everest, E

    # special characters are turned into plain ASCII letters
    def test_clean(self):
        self.assertEqual(clean("Kriva&#328;"), "Krivan")                # entity with ;
        self.assertEqual(clean("&#352trbsk&#233 Pleso"), "Strbske Pleso")  # entity without ;
        self.assertEqual(clean("Wołowiec"), "Wolowiec")                 # letter without an accent
        self.assertEqual(clean("Großer"), "Grosser")
        self.assertEqual(clean("Galdhøpiggen"), "Galdhopiggen")
        self.assertEqual(clean("Pu‘u Koa‘e"), "Pu'u Koa'e")             # curly quotes
        self.assertEqual(clean("<b>Rysy</b>\n\t2503"), "Rysy 2503")     # tags, tabs and newlines out


if __name__ == "__main__":
    unittest.main()
