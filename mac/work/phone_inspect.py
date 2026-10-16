import xml.etree.ElementTree as ET
import uiautomator2 as u2

d = u2.connect('341598588000B3Z')

def show():
    print(d.app_current())
    root = ET.fromstring(d.dump_hierarchy())
    for n in root.iter('node'):
        if n.get('package') in ('com.bytedance.lifeservice.crm', 'com.bytedance.ls.merchant') and (n.get('text') or n.get('content-desc') or n.get('class') == 'android.widget.EditText'):
            print({k: n.get(k) for k in ('text', 'content-desc', 'resource-id', 'bounds')})

if __name__ == '__main__':
    show()
