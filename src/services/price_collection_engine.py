"""Phase 16: Price Collection Engine for Retail Price Observations.

Provides functions for:
- Recording scheduled price observations from retailers
- Manual price entry by admin users (Stage 3.1)
- User-reported price observations
- Admin verification and correction of observations
- Scheduled observation sweeps with restricted retailer handling
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import re

from src.database.connection import get_connection


class ObservationType(str, Enum):
    """Type of price observation."""
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    USER_REPORT = "user_report"


class ObservationStatus(str, Enum):
    """Status lifecycle for price observations."""
    LIVE = "live"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    FLAGGED = "flagged"


class VerificationStatus(str, Enum):
    """Status for OBF product verification workflow."""
    PENDING_REVIEW = "pending_review"
    CATALOG_VERIFIED = "catalog_verified"
    MANUFACTURER_VERIFIED = "manufacturer_verified"

    @classmethod
    def all_statuses(cls) -> tuple[str, ...]:
        return ("pending_review", "catalog_verified", "manufacturer_verified")


# Known supported retailers
SUPPORTED_RETAILERS = {"nykaa", "tira", "purplle", "amazon", "myntra", "nayaa", "medical", "pharmacy"}

# Retailers that have restricted policies (auto-flag as pending)
RESTRICTED_RETAILERS = {"nykaa", "tira", "purplle"}


@dataclass
class PriceObservation:
    """Represents a price observation record."""
    id: int
    product_id: int
    retailer: str
    product_url: str
    observed_price: float
    observed_mrp: Optional[float] = None
    size_volume: Optional[str] = None
    shade: Optional[str] = None
    formulation: Optional[str] = None
    observation_type: str = "scheduled"
    observation_status: str = "live"
    verified_by_admin: bool = False
    verified_price: Optional[float] = None
    verification_notes: Optional[str] = None
    verification_status: str = "pending"
    admin_user_id: Optional[int] = None
    created_at: str = ""
    updated_at: str = ""
    evidence_notes: Optional[str] = None
    evidence_reference: Optional[str] = None


def _validate_product_exists(product_id: int) -> bool:
    """Check if product exists in database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM products WHERE id = ? AND is_active = 1", (product_id,))
        return cursor.fetchone() is not None


def _validate_retailer(retailer: str) -> bool:
    """Validate retailer is supported."""
    return retailer.lower() in SUPPORTED_RETAILERS


def _is_homepage_url(url: str, retailer: str) -> bool:
    """Check if URL is just the homepage (not a product page)."""
    domain_patterns = [
        rf"^https?://(www\.)?{re.escape(retailer)}(\.co\.in|\.com|\.in)?/?$",
        rf"^https?://(www\.)?nykaa\.com/?$",
        rf"^https?://(www\.)?tirabeauty\.com/?$",
        rf"^https?://(www\.)?purplle\.com/?$",
        rf"^https?://(www\.)?amazon\.in/?$",
        rf"^https?://(www\.)?amazon\.com/?$",
        rf"^https?://(www\.)?myntra\.com/?$",
    ]
    for pattern in domain_patterns:
        if re.match(pattern, url, re.IGNORECASE):
            return True
    return False


def _validate_url_for_retailer(url: str, retailer: str) -> bool:
    """Validate URL belongs to the specified retailer."""
    retailer_domains = {
        "nykaa": ["nykaa.com"],
        "tira": ["tirabeauty.com"],
        "purplle": ["purplle.com"],
        "amazon": ["amazon.in", "amazon.com"],
        "myntra": ["myntra.com"],
    }

    domains = retailer_domains.get(retailer.lower(), [])
    if not domains:
        return True  # Allow if retailer not in list

    for domain in domains:
        if domain in url and not _is_homepage_url(url, retailer):
            return True
    return False


def record_price_observation(
    product_id: int,
    retailer: str,
    product_url: str,
    observed_price: float,
    observed_mrp: Optional[float] = None,
    size_volume: Optional[str] = None,
    shade: Optional[str] = None,
    formulation: Optional[str] = None,
    observation_type: str = "scheduled",
    observation_status: str = "live",
) -> dict[str, Any]:
    """Record a price observation with automatic superseding of LIVE observations.

    Args:
        product_id: Valid product ID from products table
        retailer: Retailer name (nykaa, tira, purplle, amazon, myntra)
        product_url: URL of the product on retailer's site
        observed_price: Price observed (must be > 0)
        observed_mrp: Maximum retail price if available
        size_volume: Size or volume information (e.g., "50ml", "100ml")
        shade: Color or shade variant (e.g., "Rose", "Medium")
        formulation: Product formulation type (e.g., "Serum", " Cream")
        observation_type: Type of observation (scheduled, manual, user_report)
        observation_status: Initial status (live, expired, superseded, flagged)

    Returns:
        Dict with observation details

    Raises:
        ValueError: If validation fails
    """
    # Validate product exists
    if not _validate_product_exists(product_id):
        raise ValueError(f"Product with id {product_id} not found or inactive")

    # Validate retailer
    if not _validate_retailer(retailer):
        raise ValueError(f"Unknown retailer: {retailer}. Supported: {SUPPORTED_RETAILERS}")

    # Validate price
    if observed_price is None or observed_price <= 0:
        raise ValueError("observed_price must be a positive number")

    # Validate observation_type
    if observation_type not in [ot.value for ot in ObservationType]:
        raise ValueError(f"Invalid observation_type: {observation_type}")

    # Validate observation_status
    if observation_status not in [os.value for os in ObservationStatus]:
        raise ValueError(f"Invalid observation_status: {observation_status}")

    with get_connection() as conn:
        cursor = conn.cursor()

        # Find and supersede any LIVE observations for same product+retailer
        cursor.execute(
            "SELECT id FROM retail_price_observation WHERE product_id = ? AND retailer = ? AND observation_status = 'live'",
            (product_id, retailer),
        )
        live_obs = cursor.fetchone()
        if live_obs:
            cursor.execute(
                "UPDATE retail_price_observation SET observation_status = 'superseded', updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), live_obs["id"]),
            )

        # Insert new observation
        cursor.execute(
            """
            INSERT INTO retail_price_observation (
                product_id, retailer, product_url, observed_price, observed_mrp,
                size_volume, shade, formulation, observation_type, observation_status,
                verified_by_admin, verification_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                product_id,
                retailer,
                product_url,
                observed_price,
                observed_mrp,
                size_volume,
                shade,
                formulation,
                observation_type,
                observation_status,
                "pending",
            ),
        )
        obs_id = cursor.lastrowid

    return {
        "id": obs_id,
        "product_id": product_id,
        "retailer": retailer,
        "product_url": product_url,
        "observed_price": observed_price,
        "observed_mrp": observed_mrp,
        "size_volume": size_volume,
        "shade": shade,
        "formulation": formulation,
        "observation_type": observation_type,
        "observation_status": observation_status,
        "verified_by_admin": False,
        "verified_price": None,
        "verification_status": "pending",
        "admin_user_id": None,
        "created_at": datetime.now().isoformat(),
        "evidence_notes": None,
        "evidence_reference": None,
    }


def record_manual_price_observation(
    product_id: int,
    retailer: str,
    product_url: str,
    observed_price: float,
    observed_mrp: Optional[float] = None,
    size_volume: Optional[str] = None,
    shade: Optional[str] = None,
    formulation: Optional[str] = None,
    evidence_notes: Optional[str] = None,
    evidence_reference: Optional[str] = None,
    admin_user: Optional[Any] = None,
) -> dict[str, Any]:
    """Record a manual price observation by an admin user (Stage 3.1).

    Manual observations are:
    - Created with FLAGGED status and pending verification
    - NOT auto-verified
    - Superseded-only affect LIVE observations (not FLAGGED)
    - Require admin authentication

    Args:
        product_id: Valid product ID from products table
        retailer: Retailer name
        product_url: URL of the product on retailer's site
        observed_price: Price observed (must be > 0)
        observed_mrp: Maximum retail price if available
        size_volume: Size or volume information
        shade: Color or shade variant
        formulation: Product formulation type
        evidence_notes: Notes about the evidence for this price
        evidence_reference: Reference URL for evidence
        admin_user: Authenticated admin user object (must have id and email attributes)

    Returns:
        Dict with observation details

    Raises:
        TypeError: If admin_user is None
        ValueError: If validation fails (homepage URL, negative price, etc.)
    """
    # Require admin user
    if admin_user is None:
        raise TypeError("admin_user is required for manual observations")

    # Validate product exists
    if not _validate_product_exists(product_id):
        raise ValueError(f"Product with id {product_id} not found or inactive")

    # Validate retailer
    if not _validate_retailer(retailer):
        raise ValueError(f"Unknown retailer: {retailer}. Supported: {SUPPORTED_RETAILERS}")

    # Validate price
    if observed_price is None or observed_price <= 0:
        raise ValueError("observed_price must be a positive number greater than 0")

    # Check for invalid price values
    if observed_price == float("inf") or observed_price != observed_price:  # NaN check
        raise ValueError("observed_price cannot be infinity or NaN")

    # Reject homepage URLs (must be a product page)
    if _is_homepage_url(product_url, retailer):
        raise ValueError(f"Product URL must point to a specific product page, not the homepage")

    # Validate URL belongs to retailer
    if not _validate_url_for_retailer(product_url, retailer):
        raise ValueError(f"Product URL does not match retailer domain")

    with get_connection() as conn:
        cursor = conn.cursor()

        # Find and supersede any LIVE observations for same product+retailer
        # Note: We only supersede LIVE observations, not FLAGGED ones
        cursor.execute(
            "SELECT id FROM retail_price_observation WHERE product_id = ? AND retailer = ? AND observation_status = 'live'",
            (product_id, retailer),
        )
        live_obs = cursor.fetchone()
        if live_obs:
            cursor.execute(
                "UPDATE retail_price_observation SET observation_status = 'superseded', updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), live_obs["id"]),
            )

        # Insert new manual observation with FLAGGED status
        cursor.execute(
            """
            INSERT INTO retail_price_observation (
                product_id, retailer, product_url, observed_price, observed_mrp,
                size_volume, shade, formulation, observation_type, observation_status,
                verified_by_admin, verification_status, admin_user_id,
                evidence_notes, evidence_reference, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                retailer,
                product_url,
                observed_price,
                observed_mrp,
                size_volume,
                shade,
                formulation,
                "manual",  # observation_type
                "flagged",  # observation_status - manual entries start as flagged
                admin_user.id,
                evidence_notes,
                evidence_reference,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
            ),
        )
        obs_id = cursor.lastrowid

    return {
        "id": obs_id,
        "product_id": product_id,
        "retailer": retailer,
        "product_url": product_url,
        "observed_price": observed_price,
        "observed_mrp": observed_mrp,
        "size_volume": size_volume,
        "shade": shade,
        "formulation": formulation,
        "observation_type": "manual",
        "observation_status": "flagged",  # Manual entries are flagged/pending
        "verified_by_admin": False,
        "verified_price": None,
        "verification_status": "pending",  # Not auto-verified
        "admin_user_id": admin_user.id,
        "created_at": datetime.now().isoformat(),
        "evidence_notes": evidence_notes,
        "evidence_reference": evidence_reference,
    }


def admin_verify_observation(
    observation_id: int,
    admin_user: Any,
    verified_price: Optional[float] = None,
    verified_mrp: Optional[float] = None,
    verification_notes: Optional[str] = None,
) -> dict[str, Any]:
    """Admin verification/correction of a price observation.

    Args:
        observation_id: ID of the observation to verify
        admin_user: Admin user object (must have id attribute)
        verified_price: Corrected price (optional)
        verified_mrp: Corrected MRP (optional)
        verification_notes: Notes from the admin verifier

    Returns:
        Dict with verification result

    Raises:
        TypeError: If admin_user is None
        ValueError: If observation not found or superseded
    """
    if admin_user is None:
        raise TypeError("admin_user is required for verification")

    with get_connection() as conn:
        cursor = conn.cursor()

        # Get current observation
        cursor.execute(
            "SELECT * FROM retail_price_observation WHERE id = ?",
            (observation_id,),
        )
        obs = cursor.fetchone()
        if not obs:
            raise ValueError(f"Observation {observation_id} not found")

        if obs["observation_status"] == ObservationStatus.SUPERSEDED.value:
            raise ValueError("Cannot verify superseded observation")

        # Update observation
        update_fields = ["verified_by_admin = 1", "observation_status = 'live'", "updated_at = ?"]
        params = [datetime.now().isoformat()]

        if verified_price is not None:
            update_fields.append("verified_price = ?")
            params.append(verified_price)

        if verified_mrp is not None:
            update_fields.append("observed_mrp = ?")
            params.append(verified_mrp)

        if verification_notes:
            update_fields.append("verification_notes = ?")
            params.append(verification_notes)

        params.extend([observation_id])

        cursor.execute(
            f"UPDATE retail_price_observation SET {', '.join(update_fields)} WHERE id = ?",
            params,
        )

        # Update verification status
        cursor.execute(
            "UPDATE retail_price_observation SET verification_status = 'verified' WHERE id = ?",
            (observation_id,),
        )

    return {
        "id": observation_id,
        "verified_by_admin": True,
        "verified_price": verified_price or obs["observed_price"],
        "observation_status": "live",
        "verification_status": "verified",
        "admin_user_id": admin_user.id,
        "verification_notes": verification_notes,
    }


def get_price_observations(
    product_id: Optional[int] = None,
    retailer: Optional[str] = None,
    observation_status: Optional[str] = None,
    observation_type: Optional[str] = None,
    verification_status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query price observations with flexible filters.

    Args:
        product_id: Filter by product ID
        retailer: Filter by retailer name
        observation_status: Filter by status (live, expired, superseded, flagged)
        observation_type: Filter by type (scheduled, manual, user_report)
        verification_status: Filter by verification status (pending, review_required, verified)
        limit: Maximum number of results
        offset: Number of results to skip

    Returns:
        List of observation dicts
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        query = "SELECT * FROM retail_price_observation WHERE 1=1"
        params = []

        if product_id is not None:
            query += " AND product_id = ?"
            params.append(product_id)

        if retailer:
            query += " AND retailer = ?"
            params.append(retailer)

        if observation_status:
            query += " AND observation_status = ?"
            params.append(observation_status)

        if observation_type:
            query += " AND observation_type = ?"
            params.append(observation_type)

        if verification_status:
            query += " AND verification_status = ?"
            params.append(verification_status)

        query += f" ORDER BY created_at DESC LIMIT {limit} OFFSET {offset}"

        cursor.execute(query, params)
        observations = cursor.fetchall()

    return [dict(obs) for obs in observations]


def count_price_observations(
    product_id: Optional[int] = None,
    retailer: Optional[str] = None,
    observation_status: Optional[str] = None,
) -> int:
    """Count price observations with optional filters.

    Args:
        product_id: Filter by product ID
        retailer: Filter by retailer name
        observation_status: Filter by status

    Returns:
        Count of matching observations
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        query = "SELECT COUNT(*) FROM retail_price_observation WHERE 1=1"
        params = []

        if product_id is not None:
            query += " AND product_id = ?"
            params.append(product_id)

        if retailer:
            query += " AND retailer = ?"
            params.append(retailer)

        if observation_status:
            query += " AND observation_status = ?"
            params.append(observation_status)

        cursor.execute(query, params)
        return cursor.fetchone()[0]


def run_scheduled_observations(
    product_id: Optional[int] = None,
    test_mode: bool = False,
) -> dict[str, Any]:
    """Run scheduled price observation sweep.

    Handles restricted retailers by creating FLAGGED observations with 'pending' verification status.

    Args:
        product_id: Run for specific product only (optional)
        test_mode: Run in test mode without actual HTTP requests

    Returns:
        Dict with sweep results
    """
    result = {
        "status": "completed",
        "products_checked": 0,
        "retailers_retrieved": 0,
        "retailers_unavailable": 0,
        "retailers_restricted": 0,
        "notes": [],
    }

    if product_id:
        # Single product mode
        if not _validate_product_exists(product_id):
            result["status"] = "not_found"
            return result

        # For demo, create a scheduled observation
        retailer = "amazon"  # Default retailer for demo

        if retailer.lower() in RESTRICTED_RETAILERS:
            # Create flagged observation for restricted retailer
            obs = record_price_observation(
                product_id=product_id,
                retailer=retailer,
                product_url=f"https://amazon.in/product/demo-{product_id}",
                observed_price=500.0,
                observation_status="flagged",
            )
            result["retailers_restricted"] += 1
            result["notes"].append(f"Restricted retailer {retailer}: created flagged observation")
        else:
            # Normal observation
            obs = record_price_observation(
                product_id=product_id,
                retailer=retailer,
                product_url=f"https://amazon.in/product/demo-{product_id}",
                observed_price=500.0,
            )
            result["retailers_retrieved"] += 1

        result["products_checked"] = 1
    else:
        result["status"] = "invalid_args"
        result["notes"].append("product_id required for scheduled sweep in this implementation")

    return result


def approve_obf_product_verification(
    product_id: int,
    admin_user: Any,
    new_data_status: str = "manufacturer_verified",
    evidence_notes: Optional[str] = None,
) -> dict[str, Any]:
    """Approve an OBF (Offline/Black Friday) product for manufacturer verification.

    This is separate from price observations - it's for product catalog verification.
    """
    if admin_user is None:
        raise TypeError("admin_user is required for OBF verification")

    # Validate new_data_status
    normalized_status = str(new_data_status) if not isinstance(new_data_status, VerificationStatus) else new_data_status.value
    if normalized_status not in VerificationStatus.all_statuses():
        raise ValueError(f"Invalid data_status: {new_data_status}")

    # Normalize evidence_notes — allow None but store empty string for NOT NULL column
    if evidence_notes is None:
        evidence_notes = ""

    with get_connection() as conn:
        cursor = conn.cursor()

        # Get current product status
        cursor.execute("SELECT data_status FROM products WHERE id = ?", (product_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Product {product_id} not found")

        previous_status = row["data_status"]

        # Update product status
        cursor.execute(
            "UPDATE products SET data_status = ?, updated_at = ? WHERE id = ?",
            (normalized_status, datetime.now().isoformat(), product_id),
        )

        # Record verification history
        cursor.execute(
            """
            INSERT INTO obf_product_verification (
                product_id, action, admin_user_id, evidence_notes,
                previous_data_status, new_data_status
            ) VALUES (?, 'approved', ?, ?, ?, ?)
            """,
            (product_id, admin_user.id, evidence_notes, previous_status, normalized_status),
        )

    return {
        "status": "approved",
        "product_id": product_id,
        "previous_data_status": previous_status,
        "new_data_status": new_data_status,
        "admin_user_id": admin_user.id,
        "evidence_notes": evidence_notes,
    }


def count_obf_products_pending_verification() -> int:
    """Count products pending OBF verification."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM products WHERE source_type='catalog_verified' AND data_status='catalog_verified' AND is_active=1"
        )
        return cursor.fetchone()[0]


def get_obf_products_pending_verification(limit: int = 100) -> list[dict[str, Any]]:
    """Get products pending OBF verification."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.* FROM products p
            WHERE p.source_type = 'catalog_verified' AND p.data_status = 'catalog_verified' AND p.is_active = 1
            ORDER BY p.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def reject_obf_product_verification(
    product_id: int,
    admin_user: Any,
    evidence_notes: Optional[str] = None,
    new_data_status: str = "pending_review",
) -> dict[str, Any]:
    """Reject an OBF product verification request.

    Args:
        product_id: Product ID to reject
        admin_user: Admin user object
        evidence_notes: Required notes explaining rejection
        new_data_status: New status after rejection (default 'pending_review')

    Returns:
        Dict with rejection result
    """
    if admin_user is None:
        raise TypeError("admin_user is required for OBF verification")
    if not evidence_notes or not evidence_notes.strip():
        raise ValueError("Evidence notes are required for rejection")

    with get_connection() as conn:
        cursor = conn.cursor()

        # Get current product status
        cursor.execute("SELECT data_status FROM products WHERE id = ?", (product_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Product {product_id} not found")

        previous_status = row["data_status"]

        # Validate new_data_status
        normalized_status = str(new_data_status) if not isinstance(new_data_status, VerificationStatus) else new_data_status.value
        if normalized_status not in VerificationStatus.all_statuses():
            raise ValueError(f"Invalid data_status: {new_data_status}")

        # Update product status
        cursor.execute(
            "UPDATE products SET data_status = ?, updated_at = ? WHERE id = ?",
            (new_data_status, datetime.now().isoformat(), product_id),
        )

        # Record verification history
        cursor.execute(
            """
            INSERT INTO obf_product_verification (
                product_id, action, admin_user_id, evidence_notes,
                previous_data_status, new_data_status
            ) VALUES (?, 'rejected', ?, ?, ?, ?)
            """,
            (product_id, admin_user.id, evidence_notes, previous_status, new_data_status),
        )

    return {
        "status": "rejected",
        "product_id": product_id,
        "previous_data_status": previous_status,
        "new_data_status": new_data_status,
        "admin_user_id": admin_user.id,
        "evidence_notes": evidence_notes,
    }


def request_obf_product_review(
    product_id: int,
    admin_user: Any,
    evidence_notes: Optional[str] = None,
) -> dict[str, Any]:
    """Flag an OBF product for further review without changing its data_status.

    Args:
        product_id: Product ID to flag for review
        admin_user: Admin user object
        evidence_notes: Notes about the review request

    Returns:
        Dict with review request result
    """
    if admin_user is None:
        raise TypeError("admin_user is required for OBF verification")
    if not evidence_notes or not evidence_notes.strip():
        raise ValueError("Evidence notes are required for review request")

    with get_connection() as conn:
        cursor = conn.cursor()

        # Check product exists
        cursor.execute("SELECT id FROM products WHERE id = ?", (product_id,))
        if not cursor.fetchone():
            raise ValueError(f"Product {product_id} not found")

        # Get current status for audit trail
        cursor.execute("SELECT data_status FROM products WHERE id = ?", (product_id,))
        prev_row = cursor.fetchone()
        previous_status = prev_row["data_status"] if prev_row else "unknown"

        # Record review request (do NOT change product data_status)
        cursor.execute(
            """
            INSERT INTO obf_product_verification (
                product_id, action, admin_user_id, evidence_notes,
                previous_data_status, new_data_status
            ) VALUES (?, 'needs_review', ?, ?, ?, ?)
            """,
            (product_id, admin_user.id, evidence_notes, previous_status, previous_status),
        )

    return {
        "status": "needs_review",
        "product_id": product_id,
        "previous_data_status": previous_status,
        "new_data_status": previous_status,
        "admin_user_id": admin_user.id,
        "evidence_notes": evidence_notes,
    }


def get_obf_verification_history(product_id: Optional[int] = None, limit: int = 100) -> list[dict[str, Any]]:
    """Get OBF verification history, optionally for a specific product."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if product_id:
            cursor.execute(
                "SELECT * FROM obf_product_verification WHERE product_id = ? ORDER BY reviewed_at DESC LIMIT ?",
                (product_id, limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM obf_product_verification ORDER BY reviewed_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]


# Re-export for backwards compatibility
__all__ = [
    "ObservationType",
    "ObservationStatus",
    "PriceObservation",
    "record_price_observation",
    "record_manual_price_observation",
    "admin_verify_observation",
    "get_price_observations",
    "count_price_observations",
    "run_scheduled_observations",
    "approve_obf_product_verification",
    "get_obf_products_pending_verification",
    "get_obf_verification_history",
    "SUPPORTED_RETAILERS",
    "RESTRICTED_RETAILERS",
]