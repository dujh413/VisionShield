import unittest
from sensitive_rules import detect, valid_id


def line(text,y=0,x=0,confidence=.99):
    return {'text':text,'confidence':confidence,'polygon':[[x,y],[x+180,y],[x+180,y+20],[x,y+20]]}


def categories(lines):
    return {c for hit in detect(lines) for c in hit['categories']}


class SensitiveTests(unittest.TestCase):
    def test_phone_email_and_fullwidth(self):
        self.assertIn('手机号',categories([line('１３８００１３８０００')]))
        self.assertIn('邮箱',categories([line('demo@example.com')]))

    def test_plain_numbers_not_code(self):
        self.assertEqual(detect([line('今天买了123456份测试材料')]),[])

    def test_discussion_is_not_password_value(self):
        self.assertEqual(detect([line('今天讨论如何修改密码')]),[])

    def test_multiline_code_nearest_only(self):
        hits=detect([line('验证码：'),line('246810',30),line('999999',60)])
        self.assertEqual({h['line_index'] for h in hits},{0,1})

    def test_distant_digits_not_linked(self):
        hits=detect([line('验证码：'),line('246810',500)])
        self.assertEqual({h['line_index'] for h in hits},{0})

    def test_previous_row_not_linked(self):
        hits=detect([line('123456',0),line('验证码：',30)])
        self.assertEqual({h['line_index'] for h in hits},{1})

    def test_low_confidence_is_unknown(self):
        self.assertEqual(categories([line('模糊文字',confidence=.3)]),{'无法确定'})

    def test_empty_recognition_is_unknown_even_with_high_confidence(self):
        self.assertEqual(categories([line('  ',confidence=.99)]),{'无法确定'})

    def test_valid_id_and_wrong_checksum(self):
        self.assertTrue(valid_id('11010519491231002X'))
        self.assertFalse(valid_id('110105194912310021'))
        self.assertIn('身份证',categories([line('11010519491231002X')]))
        self.assertEqual(detect([line('110105194912310021')]),[])

    def test_labelled_student_account_address(self):
        for text,kind in [('学号：202600001','学号'),('账号：demo_user','账号'),
                          ('地址：虚构市测试路88号','地址'),('密码：DemoPass123','账号凭证')]:
            self.assertIn(kind,categories([line(text)]))

    def test_ordinary_chat_is_not_matched(self):
        self.assertEqual(detect([line('今天下午一起去图书馆。')]),[])


if __name__=='__main__':
    unittest.main()

