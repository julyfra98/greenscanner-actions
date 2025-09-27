# actions.py  (Rasa 3.x)
# ------------------------------------------------------------
# Acción personalizada para clasificar residuos según el "material"
# detectado en la entidad {material}. Retorna la caneca adecuada:
# BLANCA (aprovechables limpios), VERDE (orgánicos), NEGRA (no aprovechables),
# o "ESPECIAL" (pilas, electrónicos, medicamentos, aceite usado, bombillos).
# ------------------------------------------------------------

from __future__ import annotations
from typing import Any, Text, Dict, List, Optional
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.types import DomainDict
import unicodedata


def _normalize(text: str) -> str:
    """Convierte a minúsculas y elimina tildes/acentos para comparar de forma robusta."""
    if not text:
        return ""
    t = unicodedata.normalize("NFD", text.strip().lower())
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


class ActionClasificarResiduo(Action):
    def name(self) -> Text:
        return "action_clasificar_residuo"

    def __init__(self) -> None:
        # Conjuntos de ejemplos/alias por color de caneca
        # BLANCA: aprovechables limpios
        self.blanca = {
            "vidrio", "botella vidrio", "frasco vidrio",
            "plastico", "botella plastico", "botella pet", "pet", "envase plastico",
            "tapa plastico", "envase de yogur limpio", "yogur limpio",
            "metal", "lata", "lata gaseosa", "aluminio",
            "papel", "hoja papel", "papel periodico", "periodico",
            "carton", "caja carton",
            "papel aluminio limpio", "aluminio limpio",
            "tetra pak limpio", "tetrapack limpio", "tetra limpio"
        }

        # VERDE: orgánicos
        self.verde = {
            "restos comida", "restos de comida",
            "cascara banano", "cascara de banano", "cascara fruta", "cascara naranja",
            "cascara huevo", "borra cafe", "borra de cafe",
            "hojas jardin", "hojas del jardin", "podas", "poda",
            "pan viejo", "bagazo"
        }

        # NEGRA: no aprovechables (sucios/contaminados o no reciclables en el cole)
        self.negra = {
            "papel higienico", "servilletas usadas", "servilleta sucia",
            "empaques metalizados", "papel metalizado", "papel plastificado",
            "icopor", "unicel", "eps", "icopor sucio", "unicel sucio",
            "envoltura frituras", "chicle",
            "toalla sanitaria", "panal", "panales",
            "colilla cigarrillo", "mascarilla", "tapabocas",
            "papel aluminio sucio", "aluminio sucio",
            "tetra pak sucio", "tetrapack sucio", "tetra sucio",
        }

        # Palabras clave por regla (fallback semántico)
        self.rules = [
            # VERDE por orgánicos
            {"kws": ["banano", "restos", "comida", "cascara", "jardin", "hojas", "poda", "huevo", "cafe", "borra"], "color": "verde"},
            # BLANCA por aprovechables limpios
            {"kws": ["vidrio", "frasco", "lata", "aluminio", "metal", "plastico", "pet", "envase", "papel", "carton", "periodico"], "color": "blanca"},
            # NEGRA por no aprovechables/contaminados
            {"kws": ["servilleta", "higienico", "metalizado", "frituras", "icopor", "unicel", "colilla", "tapabocas", "mascarilla", "sanitaria", "panal"], "color": "negra"},
        ]

        # Residuos ESPECIALES: requieren disposición en puntos limpios o gestores
        self.especial = {
            "pila", "pilas", "bateria", "baterias",
            "electronico", "electronicos", "computador", "celular", "cargador", "e-waste",
            "medicamento", "medicamentos", "vencidos",
            "aceite usado", "aceite de cocina",
            "bombillo", "bombillos", "fluorescente", "fluorescentes",
            "termometro", "mercurio",
            "quimico", "quimicos", "pintura", "disolvente"
        }

        # Descripciones y tips por color
        self.desc = {
            "blanca": "aprovechables **limpios** (plástico, vidrio, metal, papel y cartón).",
            "verde": "residuos **orgánicos** (restos de comida, cáscaras y jardinería).",
            "negra": "**no aprovechables** (servilletas usadas, papel higiénico, empaques metalizados o sucios).",
        }
        self.tips = {
            "blanca": "Enjuaga y seca los envases para que se puedan **aprovechar**.",
            "verde": "Evita mezclar con plásticos o papel para facilitar el **compostaje**.",
            "negra": "Si está **sucio o contaminado con alimentos**, no se puede reciclar.",
        }

    # Reglas contextuales (limpio/sucio) para materiales frecuentes
    def _reglas_contexto(self, m: str) -> Optional[str]:
        # Tetra Pak: limpio → blanca; sucio → negra; sin mención → sugerimos limpieza (blanca)
        if "tetra" in m or "tetrapak" in m:
            if "sucio" in m:
                return "negra"
            return "blanca"

        # Papel aluminio: limpio → blanca; sucio → negra
        if "aluminio" in m and "papel" in m:
            if "sucio" in m:
                return "negra"
            return "blanca"

        # Envase de yogur: si dice limpio → blanca; si dice sucio → negra
        if "yogur" in m or "yogurt" in m:
            if "sucio" in m:
                return "negra"
            return "blanca"

        return None

    def _es_especial(self, m: str) -> bool:
        # si cualquier palabra especial aparece en el texto
        for kw in self.especial:
            if kw in m:
                return True
        return False

    def _decidir_caneca(self, material_raw: str) -> Optional[str]:
        m = _normalize(material_raw)

        # 1) ESPECIAL (pilas, e-waste, medicamentos, aceite usado, bombillos…)
        if self._es_especial(m):
            return "especial"

        # 2) Coincidencia exacta con conjuntos conocidos
        if m in self.blanca:
            return "blanca"
        if m in self.verde:
            return "verde"
        if m in self.negra:
            return "negra"

        # 3) Reglas de contexto (limpio/sucio) para materiales ambiguos
        cx = self._reglas_contexto(m)
        if cx:
            return cx

        # 4) Reglas por palabras clave
        for rule in self.rules:
            if any(kw in m for kw in rule["kws"]):
                return rule["color"]

        # 5) No se pudo clasificar
        return None

    async def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict
    ) -> List[Dict[Text, Any]]:

        # 1) Obtener entidad "material"
        material_entity = None
        for e in tracker.latest_message.get("entities", []):
            if e.get("entity") == "material":
                material_entity = e.get("value")
                break

        if not material_entity:
            # Si no vino la entidad, preguntar amablemente
            dispatcher.utter_message(response="utter_ask_material")
            return []

        # 2) Decidir caneca
        color = self._decidir_caneca(material_entity)

        # 3) Residuos especiales
        if color == "especial":
            msg = (
                f"El residuo **{material_entity}** es un **residuo especial**. "
                "No va en las canecas blanca/verde/negra. Debe llevarse a **puntos limpios** o "
                "**gestores autorizados** (ej.: pilas, electrónicos, medicamentos, aceite usado, bombillos). "
                "Consulta con coordinación o servicios generales del colegio sobre los puntos de acopio."
            )
            dispatcher.utter_message(text=msg)
            return []

        # 4) No se pudo clasificar
        if not color:
            dispatcher.utter_message(response="utter_cannot_classify", material=material_entity)
            return []

        # 5) Mensaje final con explicación y tip
        desc = self.desc.get(color, "")
        tip = self.tips.get(color, "")
        msg = f"El residuo **{material_entity}** va en la **caneca {color.upper()}**: {desc} {tip}".strip()
        dispatcher.utter_message(text=msg)
        return []
