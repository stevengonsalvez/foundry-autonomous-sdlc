import { render, screen } from '@testing-library/react'
import Home from '../src/pages/Home'

describe('Home Page', () => {
  it('renders a heading and sets the document title', () => {
    render(<Home />)

    // Updated copy: heading now reads "Track a parcel"
    const heading = screen.getByRole('heading', { level: 1, name: /Track a parcel/i })
    expect(heading).toBeInTheDocument()

    // Updated document title
    expect(document.title).toContain('Track a parcel')
  })
})
