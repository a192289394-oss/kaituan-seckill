import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs'))
from merchant_navigation import current_account, account_rows, profile_company, crm_candidate_nodes, MERCHANT, CRM


class NavigationTests(unittest.TestCase):
    def test_current_card_not_other_saved_card(self):
        self.assertEqual(current_account(['怡禾酒店总部子账号待办1通知18',
            '珠江宾馆总部子账号当前待办1通知20']), '珠江宾馆')

    def test_no_current_or_multiple_current_fails(self):
        for ts in [['珠江宾馆', '当前'], ['甲酒店总部子账号当前待办1', '乙酒店门店子账号当前待办0']]:
            with self.assertRaises(RuntimeError):
                current_account(ts)

    def test_company_account_distinct_from_hotel(self):
        self.assertEqual(current_account(['广州绿美乡居公寓有限公司门店子账号当前待办0']),
                         '广州绿美乡居公寓有限公司')

    def test_general_industry_current_card(self):
        self.assertEqual(current_account(['广州白天鹅酒店管理有限公司门店子账号当前']),
                         '广州白天鹅酒店管理有限公司')

    def test_only_contracted_result_is_a_candidate(self):
        def n(text, bounds):
            return f'<node package="{CRM}" class="android.widget.TextView" text="{text}" bounds="{bounds}" />'
        r=ET.fromstring('<hierarchy>'+n('线索','[45,405][189,459]')+n('错误酒店','[195,399][603,468]')+
            n('签约商家','[45,741][189,795]')+n('白天鹅迎宾馆(肇庆湖滨店)','[195,735][603,801]')+
            n('跟进人','[700,741][900,795]')+'</hierarchy>')
        self.assertEqual([n.get('text') for n in crm_candidate_nodes(r)], ['白天鹅迎宾馆(肇庆湖滨店)'])

    def test_actions_are_bound_to_their_own_account_row(self):
        prefix = MERCHANT + ':id/'
        xml = '<hierarchy><node>'
        for name, action in [('甲酒店', 'switch_account'), ('乙酒店', 'show_on_homepage')]:
            xml += f'<node><node><node text="{name}" resource-id="{prefix}account_name" /></node>'
            xml += f'<node text="button" resource-id="{prefix}{action}" /></node>'
        rows = account_rows(ET.fromstring(xml + '</node></hierarchy>'))
        self.assertEqual([r[0] for r in rows], ['甲酒店', '乙酒店'])
        self.assertIn('switch_account', rows[0][1])
        self.assertNotIn('switch_account', rows[1][1])

    def test_native_company_row_does_not_read_other_profile_fields(self):
        p = MERCHANT + ':id/'
        r = ET.fromstring(f'<hierarchy><node><node text="公司" resource-id="{p}tv_item_title" />'
            f'<node text="珠江宾馆" resource-id="{p}tv_item_hint" /></node><node>'
            f'<node text="我的账户ID" resource-id="{p}tv_item_title" />'
            f'<node text="123" resource-id="{p}tv_item_hint" /></node></hierarchy>')
        self.assertEqual(profile_company(r), '珠江宾馆')
        self.assertIsNone(profile_company(ET.fromstring('<hierarchy />')))


if __name__ == '__main__':
    unittest.main()
