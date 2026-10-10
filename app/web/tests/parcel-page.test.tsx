import { render, screen } from '@testing-library/react'
import Parcel from '../src/pages/Parcel'

describe('Parcel Page', () => {
  it('renders parcel details heading', () => {
    render(<Parcel />)

    const heading = screen.getByRole('heading', { level: 1 })
    expect(heading).toBeInTheDocument()
  })
})
