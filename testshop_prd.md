# TestShop — Product Requirements Document

## Product Overview
TestShop is a simple e-commerce platform where users can browse books, add them to cart, and complete a purchase through a checkout flow.

## User Stories

### US-001: Browse Products
**As a** shopper
**I want to** see a list of available products on the products page
**So that** I can decide what to buy

**Acceptance Criteria:**
- Products page must show at least 3 items
- Each item must show a name and price
- Each item must have a "Buy" button

### US-002: Complete Checkout
**As a** shopper
**I want to** fill my name and email and place an order
**So that** I can purchase a product

**Acceptance Criteria:**
- Checkout page must have a name input field
- Checkout page must have an email input field
- A "Place Order" button must be visible
- After placing order, user sees a confirmation page

### US-003: Learn About the Company
**As a** visitor
**I want to** read about the company on the About page
**So that** I can decide if I trust the platform

**Acceptance Criteria:**
- About page must exist at /about
- Must contain company description text
- Must contain a contact method

### US-004: Navigate the Site
**As a** user
**I want to** navigate between pages using the top navigation bar
**So that** I can access all parts of the site easily

**Acceptance Criteria:**
- Navigation must be present on every page
- Links to Home, Products, Checkout, About must all work

## Required Pages

| Page | Path | Must-Have Elements |
|---|---|---|
| Home | / | Welcome heading, Shop Now button, navigation |
| Products | /products | Product cards, prices, Buy buttons |
| Checkout | /checkout | Name field, Email field, Place Order button |
| Order Confirmation | /order-confirmed | Success message, Back to home link |
| About | /about | Company description, contact info |

## Success Metrics
- All 5 required pages load without errors
- Checkout flow completes end-to-end
- No JavaScript errors on any page
- All pages load in under 3 seconds
- Navigation works from every page

## Out of Scope
- Payment gateway integration
- User accounts / login
- Shopping cart persistence
- Mobile responsiveness
