import unittest
from app.config import Settings
from app.elder import RELATIONS, normalize, terms


class ElderTerms(unittest.TestCase):
    def test_masculine_default(self):
        t = terms('pai')
        self.assertEqual((t['label'], t['your_rel'], t['of_the'], t['he']), ('Meu pai', 'seu pai', 'do', 'ele'))

    def test_feminine(self):
        t = terms('mãe')
        self.assertEqual((t['label'], t['Your_rel'], t['of_the'], t['he']), ('Minha mãe', 'Sua mãe', 'da', 'ela'))

    def test_unknown_falls_back(self):
        self.assertEqual(normalize('cachorro'), 'pai')
        self.assertEqual(normalize(None), 'pai')
        self.assertEqual(Settings(elder_relation='Avó').elder_relation, 'avó')
        self.assertEqual(Settings().elder_relation, 'pai')

    def test_all_relations_have_terms(self):
        for relation in RELATIONS:
            self.assertTrue(terms(relation)['label'].endswith(relation))


if __name__ == '__main__':
    unittest.main()
