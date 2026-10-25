import uuid
import io
import qrcode
import qrcode.image.svg

class QRService:
    """
    Secure QR Code Service.
    Rule: NO Patient PII (Name, Phone, Age, Gender, etc.) is embedded in the QR payload.
    The QR payload contains ONLY a secure random token reference string (UUID4).
    Uses pure SVG vector rendering (zero native library compiler dependencies).
    """
    
    @staticmethod
    def generate_secure_token_hash():
        """Generates a secure, non-guessable random token hash reference."""
        return f"qr_sec_{uuid.uuid4().hex}"
        
    @staticmethod
    def generate_qr_base64(qr_code_hash):
        """
        Renders an SVG string of the QR code containing ONLY the secure token hash.
        Returns pure SVG vector XML suitable for inline HTML rendering.
        """
        factory = qrcode.image.svg.SvgPathImage
        img = qrcode.make(qr_code_hash, image_factory=factory)
        
        stream = io.BytesIO()
        img.save(stream)
        svg_xml = stream.getvalue().decode('utf-8')
        return svg_xml
