import unittest

from my_chat_bot.attachments import IncomingAttachment, classify_attachment, decode_text_attachment


class AttachmentTests(unittest.TestCase):
    def test_classify_attachment_recognizes_supported_types(self) -> None:
        self.assertEqual(classify_attachment("image.png", "image/png"), "image")
        self.assertEqual(classify_attachment("report.pdf", "application/pdf"), "pdf")
        self.assertEqual(
            classify_attachment(
                "contract.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            "rich_document",
        )
        self.assertEqual(classify_attachment("legacy.doc", "application/msword"), "rich_document")
        self.assertEqual(
            classify_attachment(
                "report.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            "spreadsheet",
        )
        self.assertEqual(classify_attachment("notes.txt", "text/plain"), "text")

    def test_decode_text_attachment_supports_utf8(self) -> None:
        self.assertEqual(decode_text_attachment("привет".encode("utf-8")), "привет")

    def test_text_attachment_becomes_input_text(self) -> None:
        attachment = IncomingAttachment(
            kind="text",
            filename="notes.txt",
            mime_type="text/plain",
            data="hello".encode("utf-8"),
        )

        parts = attachment.to_content_parts()

        self.assertEqual(parts[0]["type"], "input_text")
        self.assertIn("Содержимое файла notes.txt:\nhello", parts[0]["text"])

    def test_rich_document_becomes_input_file(self) -> None:
        attachment = IncomingAttachment(
            kind="rich_document",
            filename="contract.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            data=b"PK\x03\x04docx",
        )

        parts = attachment.to_content_parts()

        self.assertEqual(parts[0]["type"], "input_file")
        self.assertEqual(parts[0]["filename"], "contract.docx")
        self.assertTrue(
            parts[0]["file_data"].startswith(
                "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,"
            )
        )

    def test_spreadsheet_becomes_input_file(self) -> None:
        attachment = IncomingAttachment(
            kind="spreadsheet",
            filename="report.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            data=b"PK\x03\x04xlsx",
        )

        parts = attachment.to_content_parts()

        self.assertEqual(parts[0]["type"], "input_file")
        self.assertEqual(parts[0]["filename"], "report.xlsx")
        self.assertTrue(
            parts[0]["file_data"].startswith(
                "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,"
            )
        )

    def test_attachment_summary_description_is_human_readable(self) -> None:
        attachment = IncomingAttachment(
            kind="pdf",
            filename="spec.pdf",
            mime_type="application/pdf",
            data=b"%PDF-1.4",
        )

        self.assertEqual(
            attachment.summary_description(),
            'Пользователь прикрепил PDF "spec.pdf".',
        )


if __name__ == "__main__":
    unittest.main()
