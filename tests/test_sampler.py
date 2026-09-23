"""`promodeler character random`: seeded, valid, within the anthropometric ranges, and steerable by sex and style."""

import unittest

from promodeler.character import sampler
from promodeler.character.catalog import Catalog
from promodeler.core import ModelingError


class SamplerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        cls.presets = sampler.load_presets()

    def test_same_seed_same_recipe_and_seeds_differ(self):
        a, _ = sampler.sample_character(42, self.catalog, self.presets)
        b, _ = sampler.sample_character(42, self.catalog, self.presets)
        c, _ = sampler.sample_character(43, self.catalog, self.presets)
        self.assertEqual(a.canonical(), b.canonical())
        self.assertNotEqual(a.canonical(), c.canonical())
        self.assertEqual(a.id, "random-0000002a")
        self.assertEqual(a.source.kind, "random")
        self.assertEqual(a.source.sha256, self.presets["_sha256"])
        self.assertEqual(a.source.catalog_version, self.catalog.version)

    def test_two_hundred_recipes_validate_within_the_adult_ranges(self):
        sexes = set()
        for seed in range(200):
            recipe, warnings = sampler.sample_character(seed, self.catalog, self.presets)
            warnings += recipe.validate(self.catalog)
            codes = {w.code for w in warnings}
            self.assertFalse(any(code.startswith("measurements.") for code in codes), (seed, warnings))
            self.assertLessEqual(codes - {"catalog.placeholder"}, set(), (seed, codes))
            m = recipe.body.measurements_m
            girths = m.circumferences
            self.assertLess(girths["waist"], girths["hip"])
            self.assertTrue(all(s.circumference == girths[s.landmark] for s in m.cross_sections))
            self.assertTrue(all(s.width is None and s.depth is None for s in m.cross_sections))
            self.assertTrue(recipe.wardrobe, seed)
            self.assertTrue(any(g.slot == "footwear" for g in recipe.wardrobe), seed)
            self.assertTrue(recipe.appearance.hair.style, seed)
            sexes.add(recipe.identity.sex)
        self.assertEqual(sexes, {"male", "female"})

    def test_sex_and_style_can_be_fixed(self):
        recipe, _ = sampler.sample_character(5, self.catalog, self.presets, sex="male", style="business")
        self.assertEqual(recipe.identity.sex, "male")
        self.assertEqual(recipe.base.race, "human_male")
        self.assertIn("style:business", recipe.identity.descriptors)
        self.assertIn("suit_jacket_2button_01", [g.catalog_id for g in recipe.wardrobe])
        female, _ = sampler.sample_character(5, self.catalog, self.presets, sex="female", style="sport")
        self.assertEqual(female.base.race, "human_female")
        self.assertIn("bust", female.body.measurements_m.circumferences)
        self.assertNotIn("chest", female.body.measurements_m.circumferences)
        with self.assertRaises(ModelingError) as ctx:
            sampler.sample_character(5, self.catalog, self.presets, style="tuxedo")
        self.assertEqual(ctx.exception.code, "presets.style")

    def test_many_uses_consecutive_seeds(self):
        recipes = sampler.sample_many(10, 3, self.catalog, self.presets)
        self.assertEqual([r.seed for r, _ in recipes], [10, 11, 12])


if __name__ == "__main__":
    unittest.main()
