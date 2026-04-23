import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useUi } from '../contexts/UiContext';
import translations from '../translations';
import './TicketsPage.css';

type OperatorCard = {
    name: string;
    description: string;
    url: string;
};

const busOperators: OperatorCard[] = [
    {
        name: 'Stagecoach',
        description: 'Buy bus tickets and passes directly from Stagecoach.',
        url: 'https://www.stagecoachbus.com/',
    },
    {
        name: 'Blackpool Transport',
        description: 'Official Blackpool bus and tram ticket options.',
        url: 'https://www.blackpooltransport.com/',
    },
];

const railOperators: OperatorCard[] = [
    {
        name: 'National Rail',
        description: 'Plan and buy UK rail tickets via the official National Rail portal.',
        url: 'https://www.nationalrail.co.uk/',
    },
    {
        name: 'Avanti West Coast',
        description: 'Official Avanti West Coast tickets and travel information.',
        url: 'https://www.avantiwestcoast.co.uk/',
    },
];

const TicketsPage: React.FC = () => {
    const navigate = useNavigate();
    const { language } = useUi();
    const t = translations[language.code] || translations.en;
    const title = typeof (t as any).tickets === 'string' ? (t as any).tickets : 'Tickets';

    return (
        <main className="tickets-page">
            <div className="tickets-page__container">
                <div className="tickets-page__header-row">
                    <h2 className="tickets-page__title">{title}</h2>
                    <button
                        type="button"
                        className="tickets-page__plan-btn"
                        onClick={() => navigate('/')}
                    >
                        Plan Journey
                    </button>
                </div>

                <section className="tickets-section" aria-label="Bus Tickets">
                    <h3 className="tickets-section__title">Bus Tickets</h3>
                    <div className="tickets-grid">
                        {busOperators.map((op) => (
                            <article key={op.name} className="ticket-card">
                                <h4 className="ticket-card__name">{op.name}</h4>
                                <p className="ticket-card__desc">{op.description}</p>
                                <a
                                    className="ticket-card__button"
                                    href={op.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                >
                                    Buy Tickets
                                </a>
                            </article>
                        ))}
                    </div>
                </section>

                <section className="tickets-section" aria-label="Rail Tickets">
                    <h3 className="tickets-section__title">Rail Tickets</h3>
                    <div className="tickets-grid">
                        {railOperators.map((op) => (
                            <article key={op.name} className="ticket-card">
                                <h4 className="ticket-card__name">{op.name}</h4>
                                <p className="ticket-card__desc">{op.description}</p>
                                <a
                                    className="ticket-card__button"
                                    href={op.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                >
                                    Buy Tickets
                                </a>
                            </article>
                        ))}
                    </div>
                </section>
            </div>
        </main>
    );
};

export default TicketsPage;
